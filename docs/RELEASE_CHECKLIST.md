# v1.0.1 Release Checklist

- [x] `master` CI（Python 3.11/3.12 + Ruff）全绿
- [x] Windows install smoke 全绿
- [x] real OCR workflow 至少一个真实推理测试通过，非全 skip
- [x] `python scripts/verify_release.py` 通过
- [x] 关键 0.5→0.15 FinalResult/Excel E2E 通过
- [x] `python scripts/doctor.py --json` 非 BROKEN
- [x] version / CHANGELOG / Release Notes 均为 1.0.1
- [x] PR #2 merge commit 已进入 master
- [x] bundle 与 SHA-256 已生成
- [x] tag 指向已验证 master SHA
- [x] GitHub Release 资产上传成功
