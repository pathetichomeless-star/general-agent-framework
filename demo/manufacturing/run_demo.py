"""Run the Hongsheng Works governed manufacturing demo.

Public Simulation Mode (default) is fully deterministic, network-free and
independently runnable — it does not use or require any licensed framework.

    python3 demo/manufacturing/run_demo.py                 # http://127.0.0.1:8765
    python3 demo/manufacturing/run_demo.py --lang en
    python3 demo/manufacturing/run_demo.py --reset         # reseed the demo data

Licensed Framework Mode (optional, private) binds the same application to a
separately licensed backend via configuration; it is never bundled here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BANNER = """
==============================================================
 宏晟智造 Hongsheng Works · Governed Manufacturing Demo
==============================================================
 模式 Mode         : {mode}
 地址 URL          : http://{host}:{port}/
 语言 Language     : {lang}（登录后可切换 / switch after login）
 演示账号 Accounts : owner / factory / sales / sales2 / warehouse / admin
 密码 Password     : demo1234
 数据库 Database   : {db}
 说明 Note         : {note}
==============================================================
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Hongsheng Works manufacturing demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    parser.add_argument("--backend", default="public", choices=["public", "licensed"])
    parser.add_argument("--db", default=str(HERE / ".state" / "demo.sqlite"))
    parser.add_argument("--reset", action="store_true", help="delete the demo database first")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from framework_port.dtos import BackendConfig
    from framework_port import constants as _c

    if args.backend == "licensed":
        import os
        module_name = os.environ.get("HONGSHENG_LICENSED_BACKEND_MODULE", "").strip()
        if not module_name:
            print(
                "Licensed Framework Mode 需要持牌适配器：请设置 HONGSHENG_LICENSED_BACKEND_MODULE。\n"
                "Licensed Framework Mode requires the licensed adapter package; set\n"
                "HONGSHENG_LICENSED_BACKEND_MODULE to its module name. 公共演示请使用默认模式。\n"
                "For the public demo, run without --backend licensed.",
                file=sys.stderr,
            )
            return 2
        import importlib
        module = importlib.import_module(module_name)  # owner-provided, private
        create = module.create_backend
        mode_note = "LICENSED FRAMEWORK MODE（连接私有持牌框架）"
    else:
        from backend_sim import create_backend
        mode_note = ("公共模拟模式：确定性演示，不连接任何真实系统，"
                     "不代表商业框架运行时。Public simulation: not a licensed runtime.")

    from app.external_sims import SimulatedCarrier
    from app import http_server, policy, seed as seed_mod

    config = BackendConfig(
        db_path=str(db_path),
        external_systems={_c.GOVERNED_CARRIER_DISPATCH: SimulatedCarrier()},
        bootstrap_users=tuple(seed_mod.USERS),
    )
    backend = create_backend(config)

    backend.configure_authorization(
        policy._RULES, policy.APPROVAL_POLICIES, policy.APPROVER_ROLES
    )
    summary = seed_mod.seed(backend)

    app = http_server.DemoApp(backend, mode="public", default_lang=args.lang)
    print(BANNER.format(
        mode=("LICENSED FRAMEWORK" if args.backend == "licensed" else "PUBLIC SIMULATION"),
        host=args.host, port=args.port, lang=args.lang, db=db_path, note=mode_note,
    ))
    print(f"seed: {summary}")
    try:
        http_server.serve(app, args.host, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
