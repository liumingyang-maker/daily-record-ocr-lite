# v1.0.1 Release Checklist

- [ ] `master` CI（Python 3.11/3.12 + Ruff）全绿
- [ ] Windows install smoke 全绿
- [ ] real OCR workflow 至少一个真实推理测试通过，非全 skip
- [ ] `python scripts/verify_release.py` 通过
- [ ] 关键 0.5→0.15 FinalResult/Excel E2E 通过
- [ ] `python scripts/doctor.py --json` 非 BROKEN
- [ ] version / CHANGELOG / Release Notes 均为 1.0.1
- [ ] PR #1 merge commit 已进入 master
- [ ] bundle 与 SHA-256 已生成
- [ ] tag 指向已验证 master SHA
- [ ] GitHub Release 资产上传成功
