#!/bin/sh
# MiladyOS first-boot — hostname + console banner.
set -e

# hostname: milady-<last octet> unless node.conf sets one
HOST=$(hostname)
case "$HOST" in
    *milady*|*localhost*) 
        IP=$(hostname -I 2>/dev/null | awk '{print $1}')
        [ -n "$IP" ] && HOST="milady-${IP##*.}" && hostnamectl set-hostname "$HOST" 2>/dev/null || true
        ;;
esac

# 5-octet version baked at ISO build time (ISO/version.sh)
VERSION="$(cat /etc/milady/version 2>/dev/null || echo dev)"

cat > /etc/issue <<EOF
╔══════════════════════════════════════════════════════════════╗
║                     M I L A D Y O S                          ║
║               distributed milady infrastructure              ║
║                                                              ║
║                                                              ║
    Milady 4th, 2025
                           
                         *,,,....,  ..,,,,
                 ,,,,,,,,*,,,,,......,,,,,,,,.
              ,............,,,,,,...,,,,,,,,,,,,,,,
           ,.........................,.,,,,,,,,.........
        ,.....,,,.........,,,,,,,,,,.....,.......,,,,,,....,
      ,.,,,,,,,..,..,,,,,,,,,************,..,,,,,******,,,,.,,
     ,,,,,,,,,**,.,,,,*****,,,,,,,,,**/(##/,,,*****,,,*/**,,..,
     ,,,,,,,,//*,,,,,***,,,,,***(&&&&&&&&&&&&&&&(*****,**,,,.,,,
    ,,,,,**,,/*,,,,,***,,,,**%&&&&&&&&&&&&&&&&&&&&&****/,,,.,,,,
   .,,*,*/,,,*,,,.,,,**,,,**%&&&&&&&&&&&&&&&&&&&&&&&*,&(,,,/*,*,
   ,,*****,,,*,,*,,,,**,,,,*&&%,.(&&&&&&&&&&&&&&&&%*     .(%**,,
   ,******,,,,,,,,.,,,*/&%   ,%&&&&&&&&&&&&&&&&&&%#.   ##/ . .
   ,*****,,,,,,*,,,,,,/. (&&&&&%(#%&&&&&&&&&&&/
  ,*,***,,,,,,,*/( #*
 ,***//,,*(#(#.    %%%                    (#                 ,
 ,***%%%%%%%%%%%&&&&&&&.                 &&&&(          ... ,
,,**%%%%%%&%%&&&&&&%%%(              .  %&&&&%%.          .
,,*,(*%%%%%%&&&&&&&&%%%&% ..  ..   .. %&&&&&&%%%%%%%###%%%%
 ,*,,,,,/%%%%%%%%%%%%%%%&&%.   ,/(#%&&&&&&&&&&&%%%%%%%%%%%,,
 ,,,,,,,,,,..,%%%%%%%%%%%%&&&&&&&&&&&&&&&&&&&&&&%%%%%%%%,,,,.,
 .,,,,,,,,..........#%%%%%%%%&%&&&&&&&&&&&&&&&&%%%%%%%,,,,,,,,,
  ,,,,,,,,,,,.............#%%%%&&%%%%%%%%%%%%%%%%%%,,,,,,,,,,,,
    ,,,,,,,,,,,,............     %%%%%%%%%%%%%  ,,,,,,,,,,.,,,,
        ,,,,,,,,,..........,                         ,,,,,,*,,
║                                                              ║
║                                                              ║
║   Docker: ready   k3s: role-configured   MiladyOS: in ISO    ║
║   role: see /etc/milady/node.conf  (milady-role-switch)  ║
║   version: $VERSION                                          ║
╚══════════════════════════════════════════════════════════════╝
EOF

# Desktop variant: point the operator at the graphical session. ROLE is seeded
# by the installer / role-switch in node.conf (role-detect runs after us).
if [ -f /etc/milady/node.conf ]; then
    . /etc/milady/node.conf 2>/dev/null || true
    if [ "${ROLE:-}" = "desktop" ]; then
        printf "\nType 'startx' for the light sway desktop (docs/DESKTOP.md).\n" >> /etc/issue
    fi
fi

echo "milady-firstboot: hostname=$HOST"
