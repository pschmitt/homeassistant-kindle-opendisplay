{
  pkgs,
  upstream,
  receiver,
}:
let
  inherit (pkgs) lib;
  packages = builtins.fromJSON (builtins.readFile ./inkwell-inputs.json);
  fetch = pkgs.fetchurl;
  minirootfs = fetch {
    url = "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/armv7/alpine-minirootfs-3.24.2-armv7.tar.gz";
    sha256 = "5552f1ef2398cee46ef2cf733f8f1258f39a77ad065dfd47282fc0df9fe1976c";
  };
  llama = fetch {
    url = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/v0.7.0.tar.gz";
    sha256 = "55d67acf3ad2ad747a9bbeb75f9f0e173dbcc0d1753a471038a90c819421c5e1";
  };
  doom = fetch {
    url = "https://deb.debian.org/debian/pool/non-free/d/doom-wad-shareware/doom-wad-shareware_1.9.fixed-5_all.deb";
    sha256 = "5802f176c0303e228095b5312def53de602781cf4c53e79842257484a0d9e938";
  };
  model = fetch {
    url = "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/09816acd5d99df7be770d85ea30822623dab342c/SmolLM2-135M-Instruct-Q4_0.gguf";
    sha256 = "bcc3af2849ad6095af57e9b5cd43775256efdc66e306acb529172f92d0c04b03";
  };
  overlay = ../opendisplay;
  assetNames = map (package: lib.removeSuffix ".apk" package.name) packages.rootfs;
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "inkwell-paperwhite4-opendisplay";
  version = "1";
  src = upstream;
  patches = [ ./inkwell-external-power.patch ];
  nativeBuildInputs = [
    pkgs.binutils
    pkgs.cmake
    pkgs.e2fsprogs
    pkgs.llvmPackages.clang-unwrapped
    pkgs.llvmPackages.lld
    (lib.getBin pkgs.llvmPackages.llvm)
    pkgs.ninja
    pkgs.python314
    pkgs.zip
  ];
  dontConfigure = true;
  dontFixup = true;
  SOURCE_DATE_EPOCH = "1704067200";
  E2FSPROGS_FAKE_TIME = "1704067200";
  TZ = "UTC";
  NO_KEYS = "1";
  TZ_NAME = "UTC";

  postPatch = ''
    patchShebangs --build build-rootfs.sh build-ui.sh build-doom.sh build-llm.sh tools
    # Select the exact packages from the manifest and disable the online fallback.
    substituteInPlace build-rootfs.sh \
      --replace-fail '$(python3 tools/apkdeps.py downloads/APKINDEX.main,downloads/APKINDEX.community $PKGS)' ${lib.escapeShellArg (lib.concatStringsSep " " assetNames)} \
      --replace-fail 'curl -sf --retry 3' 'false #' \
      --replace-fail '"$MKE2FS" -q -F -t ext3 -L alpine -E root_owner=0:0' \
        'find "$S" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +; "$MKE2FS" -q -F -t ext3 -L alpine -U b5d5f13e-5420-4a0b-b2e2-1da2b17ac001 -E root_owner=0:0,hash_seed=b5d5f13e-5420-4a0b-b2e2-1da2b17ac002,lazy_itable_init=0,lazy_journal_init=0'

    export PYTHONPATH=${overlay}
    python3 - <<'PY'
    from pathlib import Path
    from install import patch_init

    path = Path("src/rootfs/sbin/own-init")
    path.write_text(patch_init(path.read_text()))
    PY
    bash -n src/rootfs/sbin/own-init
    mkdir -p src/rootfs/opt/opendisplay
    install -m 0755 ${receiver}/bin/kindle-opendisplay src/rootfs/opt/opendisplay/
    install -m 0755 ${overlay}/start ${overlay}/frontlight src/rootfs/opt/opendisplay/
    install -m 0644 ${overlay}/settings.py ${overlay}/provision.py src/rootfs/opt/opendisplay/
    touch src/rootfs/opt/opendisplay/autostart
  '';

  buildPhase = ''
    runHook preBuild
    mkdir -p downloads/{alpine,sysroot,llama,doom}
    ln -s ${minirootfs} downloads/alpine/alpine-minirootfs-3.24.2-armv7.tar.gz
    ${lib.concatMapStringsSep "\n" (
      package: "ln -s ${fetch package} downloads/alpine/${package.name}"
    ) packages.rootfs}
    ${lib.concatMapStringsSep "\n" (
      package:
      "tar -ixzf ${fetch package} -C downloads/sysroot --exclude '.SIGN*' --exclude '.PKGINFO' --exclude '.pre-*' --exclude '.post-*' --exclude '.trigger'"
    ) packages.sysroot}
    tar -xzf ${llama} -C downloads/llama
    ar p ${doom} data.tar.xz | tar -xJOf - ./usr/share/games/doom/doom1.wad > downloads/doom/doom1.wad
    printf '%s\n' '1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771  downloads/doom/doom1.wad' | sha256sum -c
    export CMAKE_BUILD_PARALLEL_LEVEL="$NIX_BUILD_CORES"
    export SIZE=1G
    ./build-rootfs.sh
    # The upstream repair pass records wall-clock timestamps in the superblock.
    printf '%s\n' "set_current_time @$SOURCE_DATE_EPOCH" "set_super_value lastcheck @$SOURCE_DATE_EPOCH" \
      | debugfs -w -f /dev/stdin out/alpine.img
    e2fsck -fn out/alpine.img
    debugfs -R 'stat /opt/opendisplay/kindle-opendisplay' out/alpine.img | grep -F 'Type: regular'
    debugfs -R 'stat /opt/opendisplay/control.key' out/alpine.img 2>&1 | grep -F 'File not found'
    debugfs -R 'stat /opt/opendisplay/device.json' out/alpine.img 2>&1 | grep -F 'File not found'
    debugfs -R 'stat /usr/bin/python3.14' out/alpine.img | grep -F 'Type: regular'
    debugfs -R 'cat /sbin/own-init' out/alpine.img | grep -F 'exec /opt/opendisplay/start'
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out" release/linux/models release/documents
    cp out/alpine.img src/linux/boot.sh src/linux/ownlinux.conf kindle/linux/wifi.conf.example release/linux/
    cp ${model} release/linux/models/smollm2-135m-q4_0.gguf
    cp kindle/documents/Inkwell\ -\ *.sh release/documents/
    printf '%s\n' UTC > release/linux/timezone
    (
      cd release
      find . -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
      find linux documents -type f | LC_ALL=C sort | zip -q -X -9 "$out/Inkwell-Paperwhite4-OpenDisplay.zip" -@
    )
    (
      cd "$out"
      sha256sum Inkwell-Paperwhite4-OpenDisplay.zip > SHA256SUMS
    )
    runHook postInstall
  '';
}
