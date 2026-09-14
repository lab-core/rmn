# Security headers of the webapp nginx. The front nginx (services/nginx/
# security_headers) adds the full set including a nonce-based CSP; these are
# the safe subset that must hold even when the webapp is reached without it.
# `always` keeps them on error pages. Included at the server level and again
# in every location that calls add_header itself (nginx drops the inherited
# ones there). The Permissions-Policy and HSTS values are byte-identical to
# the front proxy's: both are sent, a difference leaves the browser with two
# policies.
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options DENY always;
add_header Referrer-Policy strict-origin always;
add_header Permissions-Policy "geolocation=(),midi=(),sync-xhr=(),microphone=(),camera=(),magnetometer=(),gyroscope=(),fullscreen=(self),payment=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
