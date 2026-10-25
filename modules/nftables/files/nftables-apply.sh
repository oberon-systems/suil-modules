#!/bin/bash
# Applies and diffs the managed nftables ruleset. Ported from the puppet
# estate, where the same script backs the nftables module.
#
# The paths are overridable so the role does not have to assume a distribution
# layout: /etc/sysconfig exists on EL and nowhere else.
PATH=/sbin:/bin:/usr/sbin:/usr/bin

STATE_DIR="${NFT_STATE_DIR:-/var/lib/nftables}"
SYSTEM_CONFIG="${NFT_SYSTEM_CONFIG:-$STATE_DIR/ruleset.nft}"
FALLBACK_CONFIG="${NFT_FALLBACK_CONFIG:-$STATE_DIR/fallback.nft}"

die() {
    echo "nftables-apply: $2" >&2
    exit "$1"
}

nft_check() {
    [[ -f $1 ]] || die 3 "ruleset file '$1' not found"
    command -v nft >/dev/null 2>&1 ||
        die 1 "nft not found in PATH ($PATH) - is the nftables package installed?"

    # 'nft -c' parses the file and validates it against the kernel without
    # committing anything, so a bad ruleset fails the run while the live
    # firewall stays exactly as it was
    nft -c -f "$1" || die 5 "ruleset '$1' rejected, nothing applied - firewall left untouched"
}

nft_apply() {
    nft_check "$1"
    mkdir -p "$STATE_DIR" || die 1 "cannot create $STATE_DIR"

    # snapshot the live ruleset: 'nft -c' cannot catch a commit that loses a
    # race with another writer, so keep the rollback path as a second net
    {
        echo 'flush ruleset'
        nft list ruleset
    } >"$FALLBACK_CONFIG" ||
        die 1 "cannot read the current ruleset into $FALLBACK_CONFIG"

    if nft -f "$1"; then
        # saved stateless so that nft_diff can compare like with like
        nft -s list ruleset >"$SYSTEM_CONFIG" || die 1 "cannot write $SYSTEM_CONFIG"
    else
        nft -f "$FALLBACK_CONFIG" ||
            die 4 "'$1' was rejected AND the rollback failed - firewall state is undefined"
        die 2 "'$1' was rejected after passing the check, rolled back to the previous ruleset"
    fi
}

nft_diff() {
    [[ -f $SYSTEM_CONFIG ]] || return 1
    # -s drops packets/bytes: they change constantly, and comparing them made
    # every run rebuild the ruleset and reset the counters
    diff -EqbwBI "^[[:space:]]*[#*]" \
        <(sort "$SYSTEM_CONFIG") \
        <(nft -s list ruleset | sort) >/dev/null
    return $?
}

case "$1" in
diff)
    nft_diff
    ;;

check)
    nft_check "$2"
    ;;

*)
    nft_apply "$1"
    ;;
esac
