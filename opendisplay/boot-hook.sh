# Let OpenDisplay own the panel before starting Inkwell Home.
if [ -d /sys/class/power_supply/bd71827_bat ] && [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ] &&
    /opt/opendisplay/kindle-opendisplay --setting autostart; then
    if /opt/opendisplay/kindle-opendisplay --setting opendisplay; then
        (
            sleep 25
            exec /opt/opendisplay/start --boot-exclusive
        ) </dev/null >>/var/log/opendisplay.log 2>&1 &
        receiver_pid=$!
        printf '%s\n' "$receiver_pid" >/run/opendisplay.pid
        (
            sleep 45
            if { kill -0 "$receiver_pid" 2>/dev/null && [ -d /run/opendisplay-mode.lock ]; } || pidof home >/dev/null; then
                if [ -f "$U/BOOT_OWN.trying" ]; then
                    mv "$U/BOOT_OWN.trying" "$U/BOOT_OWN" && sync
                fi
            fi
        ) &
        wait "$receiver_pid"
        rm -f /run/opendisplay.pid
    fi
    if ! /opt/opendisplay/kindle-opendisplay --setting opendisplay; then
        (
            sleep 25
            exec /opt/opendisplay/start
        ) </dev/null >>/var/log/opendisplay.log 2>&1 &
        printf '%s\n' "$!" >/run/opendisplay.pid
    fi
fi

