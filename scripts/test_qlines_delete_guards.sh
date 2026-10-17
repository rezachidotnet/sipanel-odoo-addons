#!/usr/bin/env bash
# Deletion-guard test for scripts/sipanel_qlines_clone_validate.sh (2026-10-06).
# Everything happens inside a NEW sandbox directory: EVID_ROOT, FS_ROOT and LOGDIR all point into it, SUDO is
# empty. No real evidence, filestore or Production path is ever used. The sandbox must not exist beforehand.
# Usage: scripts/test_qlines_delete_guards.sh <new sandbox dir>     (e.g. /tmp/qlines-guard-test-$(date +%s))
set -euo pipefail
D=${1:?sandbox directory (must not exist)}
case "$D" in /tmp/*) ;; *) echo "sandbox must be under /tmp"; exit 2;; esac
[ ! -e "$D" ] || { echo "sandbox $D exists - choose a new one"; exit 2; }
S=$(dirname "$0")/sipanel_qlines_clone_validate.sh
mkdir -p "$D/root/quotation_lines_clone_X" "$D/root/other" "$D/logs" "$D/filestore/sipanel" \
         "$D/filestore/sipanel_qlines_clone_20990101T000000Z"
touch "$D/filestore/sipanel/canary" "$D/filestore/sipanel_qlines_clone_20990101T000000Z/att" "$D/root/other/keep"
a=$(grep -n '^refuse()' "$S" | cut -d: -f1); b=$(grep -n '^worktree_delete()' "$S" | cut -d: -f1)
sed -n "${a},$((b-1))p" "$S" > "$D/guards.sh"
E="$D/root/quotation_lines_clone_X"
touch "$E/pre_a.pdf" "$E/pre_b.json" "$E/post_c.pdf" "$E/keep.txt"; mkdir "$E/pre_dir"
FAILS=0
run() {  # $1 = expected rc class (ok|refused) ; $2 = label ; $3 = code
  local rc=0 out
  out=$(SUDO='' EVID_ROOT="$D/root" FS_ROOT="$D/filestore" LOGDIR="$D/logs" \
        CLONE_RE='^sipanel_qlines_clone_[0-9]{8}T[0-9]{6}Z$' \
        bash -euo pipefail -c "source '$D/guards.sh'; $3" 2>&1) || rc=$?
  if { [ "$1" = ok ] && [ "$rc" = 0 ]; } || { [ "$1" = refused ] && [ "$rc" != 0 ]; }; then
    echo "PASS $2 (rc=$rc)"
  else
    echo "FAIL $2 (rc=$rc, expected $1): $out"; FAILS=$((FAILS + 1))
  fi
}
must_exist() { [ -e "$1" ] && echo "PASS still exists: ${1#$D/}" || { echo "FAIL deleted: ${1#$D/}"; FAILS=$((FAILS + 1)); }; }
must_not_exist() { [ ! -e "$1" ] && echo "PASS deleted: ${1#$D/}" || { echo "FAIL still exists: ${1#$D/}"; FAILS=$((FAILS + 1)); }; }

run refused "1 empty EVID"            'EVID=""; evid_delete pre'
run refused "2 EVID=/"                'EVID=/; evid_delete pre'
run refused "3 EVID outside root"     "EVID='$D/root/other'; evid_delete pre"
run refused "4 EVID traversal"        "EVID='$D/root/quotation_lines_clone_X/../other'; evid_delete pre"
run refused "5 empty prefix"          "EVID='$E'; evid_delete ''"
run refused "6 glob prefix"           "EVID='$E'; evid_delete '*'"
must_exist "$D/root/other/keep"
run ok      "7 good prefix delete"    "EVID='$E'; evid_delete pre"
must_not_exist "$E/pre_a.pdf"; must_not_exist "$E/pre_b.json"
must_exist "$E/post_c.pdf"; must_exist "$E/keep.txt"; must_exist "$E/pre_dir"
run refused "8 outdir outside LOGDIR" "OUTDIR='$D/root'; outdir_delete"
must_exist "$D/root/other/keep"
run refused "9 outdir empty"          "OUTDIR=''; outdir_delete"
mkdir "$D/logs/.render-out.Ab12Cd"; touch "$D/logs/.render-out.Ab12Cd/x.pdf"
run ok      "10 outdir good"          "OUTDIR='$D/logs/.render-out.Ab12Cd'; outdir_delete"
must_not_exist "$D/logs/.render-out.Ab12Cd"
run refused "11 filestore CLONE=sipanel"             "CLONE='sipanel'; filestore_delete"
must_exist "$D/filestore/sipanel/canary"
run refused "11b filestore CLONE=../filestore/sipanel" "CLONE='../filestore/sipanel'; filestore_delete"
must_exist "$D/filestore/sipanel/canary"
run refused "12 filestore CLONE empty"               "CLONE=''; filestore_delete"
must_exist "$D/filestore/sipanel/canary"
ln -s "$D/filestore/sipanel" "$D/filestore/sipanel_qlines_clone_20990202T000000Z"
run refused "13 filestore clone name symlinked to sipanel" "CLONE='sipanel_qlines_clone_20990202T000000Z'; filestore_delete"
must_exist "$D/filestore/sipanel/canary"
run ok      "14 filestore real clone"                "CLONE='sipanel_qlines_clone_20990101T000000Z'; filestore_delete"
must_not_exist "$D/filestore/sipanel_qlines_clone_20990101T000000Z"
must_exist "$D/filestore/sipanel/canary"
echo "GUARD TEST: $FAILS failure(s); sandbox left in place for inspection: $D"
[ "$FAILS" = 0 ]
