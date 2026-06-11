ssh -L 8001:127.0.0.1:8000 `
  -o ProxyCommand="ssh kah044@dsmlp-login.ucsd.edu '/opt/launch-sh/bin/launch-sp26-cuda128.sh -W CSE252D_SP26_A00 -c 4 -m 16 -g 1 -l gpu-class=medium -H'" `
  kah044@dsmlp-pod
