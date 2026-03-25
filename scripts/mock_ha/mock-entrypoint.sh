#!/bin/bash
# Entrypoint wrapper for bess-dev in mock mode.
# When FAKETIME is set, activates libfaketime so BESS runs at the emulated time.
# Otherwise passes through transparently to the original command.

if [ -n "${FAKETIME:-}" ]; then
  LIBFAKETIME=$(find /usr/lib -name "libfaketime.so.1" 2>/dev/null | head -1)
  if [ -n "$LIBFAKETIME" ]; then
    export LD_PRELOAD="$LIBFAKETIME"
    echo "[mock-entrypoint] Fake time enabled: $FAKETIME (using $LIBFAKETIME)"
  else
    echo "[mock-entrypoint] WARNING: libfaketime not found, running at real time"
  fi
fi

exec "$@"
