#!/usr/bin/env bash
# Cut a Kindle OpenDisplay release and install it over the air.

REPO="pschmitt/homeassistant-kindle-opendisplay"
MANIFEST="custom_components/kindle_inkwell/manifest.json"
VERSION_FILES=(Cargo.toml Cargo.lock "$MANIFEST")

usage() {
  cat <<EOF
Usage: $(basename "$0") ACTION [ARGS]

Actions:
  prepare VERSION  Bump Cargo.toml, Cargo.lock and the integration manifest
                   to VERSION (X.Y.Z), commit and push to main.
  tag              Wait for green CI on main, push the signed tag vVERSION
                   and wait for the release workflow to publish the assets.
  ota ENTITY       Wait until the Home Assistant update ENTITY offers the
                   released version, then install it on the Kindle.
                   Needs HASS_URL and HASS_TOKEN in the environment.

Options:
  -h, --help       Show this help.
EOF
}

die() {
  printf '%s\n' "$*" >&2
  return 1
}

current_version() {
  jq -r .version "$MANIFEST"
}

ensure_synced_main() {
  git fetch -q origin main || return 1
  if [[ -n "$(git status --porcelain -- "${VERSION_FILES[@]}")" ]]
  then
    die "Uncommitted changes in the version files"
    return 1
  fi
  if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]
  then
    die "HEAD is not origin/main; pull or push first"
    return 1
  fi
}

newer_version() {
  local candidate="$1" current="$2"
  [[ "$candidate" != "$current" ]] &&
    [[ "$(printf '%s\n%s\n' "$current" "$candidate" | sort -V | tail -n 1)" == "$candidate" ]]
}

prepare() {
  local version="$1" current
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
  then
    die "VERSION must look like X.Y.Z"
    return 2
  fi
  ensure_synced_main || return 1
  current="$(current_version)" || return 1
  if ! newer_version "$version" "$current"
  then
    die "$version is not newer than $current"
    return 1
  fi

  sed -i "0,/^version = \"$current\"$/s//version = \"$version\"/" Cargo.toml || return 1
  sed -i "/^name = \"kindle-opendisplay\"$/{n;s/^version = \"$current\"$/version = \"$version\"/}" \
    Cargo.lock || return 1
  sed -i "s/\"version\": \"$current\"/\"version\": \"$version\"/" "$MANIFEST" || return 1
  if [[ "$(git diff --numstat -- "${VERSION_FILES[@]}" | wc -l)" -ne 3 ]]
  then
    git checkout -- "${VERSION_FILES[@]}"
    die "Could not bump all three version files from $current"
    return 1
  fi

  git commit -q -m "Prepare Kindle OpenDisplay $version" -- "${VERSION_FILES[@]}" || return 1
  git push -q origin HEAD:main || return 1
  printf 'Pushed %s for %s\n' "$(git rev-parse --short HEAD)" "$version"
}

wait_for_ci() {
  local commit="$1" runs pending failed
  printf 'Waiting for CI on %s' "${commit:0:7}" >&2
  while :
  do
    runs="$(gh run list -R "$REPO" --commit "$commit" --json status,conclusion)" || return 1
    pending="$(jq '[.[] | select(.status != "completed")] | length' <<< "$runs")"
    failed="$(jq '[.[] | select(.status == "completed" and .conclusion != "success")] | length' <<< "$runs")"
    if [[ "$failed" -gt 0 ]]
    then
      printf '\n' >&2
      die "CI failed on ${commit:0:7}"
      return 1
    fi
    if [[ "$(jq length <<< "$runs")" -gt 0 && "$pending" -eq 0 ]]
    then
      printf ' green\n' >&2
      return 0
    fi
    printf '.' >&2
    sleep 30
  done
}

tag() {
  local version commit run
  ensure_synced_main || return 1
  version="$(current_version)" || return 1
  if [[ "$(sed -n 's/^version = "\([0-9.]*\)"$/\1/p' Cargo.toml | head -n 1)" != "$version" ]]
  then
    die "Cargo.toml and $MANIFEST disagree on the version"
    return 1
  fi
  if git rev-parse -q --verify "refs/tags/v$version" >/dev/null
  then
    die "Tag v$version already exists; run prepare with a newer version"
    return 1
  fi
  commit="$(git rev-parse HEAD)"
  wait_for_ci "$commit" || return 1

  git tag -s "v$version" -m "Kindle OpenDisplay v$version" "$commit" || return 1
  git push -q origin "v$version" || return 1
  printf 'Pushed tag v%s\n' "$version"

  sleep 10
  run="$(gh run list -R "$REPO" --workflow release.yaml --branch "v$version" --limit 1 \
    --json databaseId --jq '.[0].databaseId')" || return 1
  if [[ -z "$run" ]]
  then
    die "No release run found for v$version"
    return 1
  fi
  gh run watch "$run" -R "$REPO" --exit-status --interval 30 >/dev/null || {
    die "Release workflow failed: https://github.com/$REPO/actions/runs/$run"
    return 1
  }
  printf 'Released https://github.com/%s/releases/tag/v%s\n' "$REPO" "$version"
}

hass() {
  local method="$1" path="$2" data="${3:-}"
  local -a args=(-fsS -X "$method" -H @-)
  if [[ -n "$data" ]]
  then
    args+=(-H 'Content-Type: application/json' -d "$data")
  fi
  # The token goes through stdin so it never appears in the process list.
  curl "${args[@]}" --max-time 900 "${HASS_URL%/}/api/$path" \
    <<< "Authorization: Bearer $HASS_TOKEN"
}

ota() {
  local entity="$1" version latest attempt
  if [[ -z "$entity" ]]
  then
    die "Missing the Home Assistant update ENTITY"
    return 2
  fi
  if [[ -z "${HASS_URL:-}" || -z "${HASS_TOKEN:-}" ]]
  then
    die "Set HASS_URL and HASS_TOKEN"
    return 2
  fi
  version="$(current_version)" || return 1
  local body
  body="$(jq -cn --arg entity "$entity" '{entity_id: $entity}')"

  # The update entity checks GitHub at most every 15 minutes, after a
  # successful status call to the Kindle, so nudge it until it sees the release.
  for attempt in $(seq 1 30)
  do
    hass POST services/homeassistant/update_entity "$body" >/dev/null || return 1
    latest="$(hass GET "states/$entity" | jq -r .attributes.latest_version)" || return 1
    if [[ "$latest" == "$version" ]]
    then
      break
    fi
    printf 'Home Assistant offers %s, waiting for %s (%s/30)\n' "$latest" "$version" "$attempt" >&2
    sleep 60
  done
  if [[ "$latest" != "$version" ]]
  then
    die "Home Assistant never offered $version"
    return 1
  fi

  if [[ "$(hass GET "states/$entity" | jq -r .attributes.in_progress)" == "true" ]]
  then
    die "An install is already in progress"
    return 1
  fi
  hass POST services/update/install "$body" >/dev/null || return 1
  hass GET "states/$entity" |
    jq -r '"Installed \(.attributes.installed_version), latest \(.attributes.latest_version)"'
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      return 0
      ;;
    prepare)
      prepare "${2:-}"
      ;;
    tag)
      tag
      ;;
    ota)
      ota "${2:-}"
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]
then
  cd "$(dirname "$0")/.." || exit 1
  main "$@"
  exit "$?"
fi

# vim: set ft=sh et ts=2 sw=2 :
