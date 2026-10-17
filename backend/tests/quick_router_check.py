import sys
sys.path.insert(0, 'backend')
from router.master_router import _parse_transform_from_message

tests = [
    ("replace Delhi with Mumbai", "REPLACE_VALUES", "Delhi", "Mumbai"),
    ("replace 0 with unknown", "REPLACE_VALUES", 0, "unknown"),
    ("replace USA with US", "REPLACE_VALUES", "USA", "US"),
    ("replace integer 0 with unknown", "REPLACE_VALUES", 0, "unknown"),
    ("replace string 0 with unknown", "REPLACE_VALUES", "0", "unknown"),
]

for msg, expected_type, expected_old, expected_new in tests:
    r = _parse_transform_from_message(msg)
    if r is None:
        print(f"FAIL [{msg}]: returned None")
        continue
    if r.get('type') != expected_type:
        print(f"FAIL [{msg}]: type={r.get('type')!r} expected={expected_type!r}")
        continue
    old_v = r.get('old_value')
    new_v = r.get('new_value')
    ok = True
    if old_v != expected_old or type(old_v) != type(expected_old):
        print(f"FAIL [{msg}]: old={old_v!r}({type(old_v).__name__}) expected={expected_old!r}({type(expected_old).__name__})")
        ok = False
    if new_v != expected_new or type(new_v) != type(expected_new):
        print(f"FAIL [{msg}]: new={new_v!r}({type(new_v).__name__}) expected={expected_new!r}({type(expected_new).__name__})")
        ok = False
    if ok:
        print(f"PASS [{msg}]")

# N/A with single-quote test
na_msg = "replace 'N/A' with 0"
r = _parse_transform_from_message(na_msg)
if r and r.get('old_value') == 'N/A' and r.get('type') == 'REPLACE_VALUES':
    print(f"PASS [{na_msg}]")
else:
    print(f"FAIL [{na_msg}]: {r}")
