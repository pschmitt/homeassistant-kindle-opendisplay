# Start OpenDisplay after Inkwell rearms its boot marker.
if [ -d /sys/class/power_supply/bd71827_bat ] && [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ]; then
    (
        sleep 25
        exec /opt/opendisplay/start
    ) </dev/null >>/var/log/opendisplay.log 2>&1 &
    printf '%s\n' "$!" >/run/opendisplay.pid
fi

