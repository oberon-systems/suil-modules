#!/bin/bash
# Refreshes the DNS backed sets of the managed ruleset, so a record that
# changes takes effect without a configuration run.
#
# The mapping is not kept anywhere: the ruleset is the mapping. Every set the
# role renders from a DNS name carries that name as its nft comment, which is
# what the sed below reads back. Change the set fragment in
# templates/nftables.conf.j2 and this stops finding anything.
PATH=/sbin:/bin:/usr/sbin:/usr/bin

RULES="${1:-/etc/nftables/suil.nft}"
STATE_DIR="${NFT_STATE_DIR:-/var/lib/nftables}"
SYSTEM_CONFIG="${NFT_SYSTEM_CONFIG:-$STATE_DIR/ruleset.nft}"

[[ -f $RULES ]] || exit 0
command -v nft >/dev/null 2>&1 || exit 0

changed=0
failed=0

live_elements() {
    # $1 family, $2 table, $3 set. The elements span several lines, so the
    # whole listing is flattened before the braces are cut out of it.
    nft -t list set "$1" "$2" "$3" 2>/dev/null |
        tr '\n' ' ' |
        sed -n 's/.*elements = {\([^}]*\)}.*/\1/p' |
        tr ',' '\n' | tr -d ' ' | sed '/^$/d' | sort -u
}

while read -r family table set name; do
    [[ -n $name ]] || continue

    wanted="$(getent ahostsv4 "$name" | awk '{print $1}' | sort -u)"
    if [[ -z $wanted ]]; then
        echo "nftables-resolve: '$name' resolves to nothing, leaving $set alone" >&2
        failed=1
        continue
    fi

    if [[ "$wanted" == "$(live_elements "$family" "$table" "$set")" ]]; then
        continue
    fi

    # One transaction, so the set is never briefly empty and never half applied
    if nft -f - <<<"flush set $family $table $set
add element $family $table $set { $(echo "$wanted" | paste -sd,) }"; then
        changed=1
        echo "nftables-resolve: $family $table $set <- $name ($(echo "$wanted" | paste -sd,))"
    else
        echo "nftables-resolve: failed to update $family $table $set from '$name'" >&2
        failed=1
    fi
done < <(sed -n 's/^add set \([^ ]*\) \([^ ]*\) \([^ ]*\) {.*comment "\([^"]*\)".*/\1 \2 \3 \4/p' "$RULES")

# The saved ruleset is what 'nftables-apply.sh diff' compares against. Without
# this every refresh would look like drift and the next configuration run would
# put the stale addresses back.
if [[ $changed -eq 1 && -f $SYSTEM_CONFIG ]]; then
    nft -s list ruleset >"$SYSTEM_CONFIG" ||
        echo "nftables-resolve: cannot rewrite $SYSTEM_CONFIG" >&2
fi

exit "$failed"
