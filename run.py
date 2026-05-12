import argparse
import asyncio
import datetime
import json
import uuid

from app.agents.base import ToolBox
from app.agents.orchestrator import create_app_graph
from app.agents.prompts import PromptRegistry
from app.config import settings
from app.memory.shared_memory import MemoryHelper
from app.tools.compliance_tool import ComplianceTool
from app.tools.file_store import FileStoreTool
from app.tools.keyword_tool import KeywordTool
from app.tools.llm_tool import LLMTool


def _init_toolbox() -> ToolBox:
    return ToolBox(
        llm=LLMTool(),
        keyword=KeywordTool(),
        compliance=ComplianceTool(),
        file_store=FileStoreTool(settings.artifacts_dir),
        prompts=PromptRegistry(),
    )


async def main():
    parser = argparse.ArgumentParser(description="Eco Listing Agent CLI")
    sub = parser.add_subparsers(dest="cmd")

    rp = sub.add_parser("run")
    rp.add_argument("--asins", required=True, help="逗号分隔的竞品 ASIN")

    sp = sub.add_parser("status")
    sp.add_argument("--run-id", required=True)

    rv = sub.add_parser("review")
    rv.add_argument("--run-id", required=True)
    rv.add_argument("--file", required=True)

    up = sub.add_parser("upload")
    up.add_argument("--run-id", required=True)
    up.add_argument("--file", required=True)
    up.add_argument(
        "--type",
        choices=["listings", "keywords", "screenshot"],
        default="listings",
    )

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    toolbox = _init_toolbox()
    graph = create_app_graph(toolbox)

    if args.cmd == "run":
        asins = [a.strip() for a in args.asins.split(",")]
        run_id = f"run_{datetime.date.today():%Y%m%d}_{uuid.uuid4().hex[:6]}"
        state = {
            "run_id": run_id,
            "competitor_asins": asins,
            "status": "running",
        }
        print(f"Starting run: {run_id}")
        result = await graph.ainvoke(
            state, {"configurable": {"thread_id": run_id}}
        )
        print(f"Status: {result.get('status')}")
        if result.get("pending_action"):
            print(
                f"Pending: {json.dumps(result['pending_action'], ensure_ascii=False, indent=2)}"
            )

    elif args.cmd == "status":
        s = graph.get_state({"configurable": {"thread_id": args.run_id}})
        print(
            json.dumps(
                {
                    "status": s.values.get("status"),
                    "pending_action": s.values.get("pending_action"),
                    "progress": {
                        k: MemoryHelper.has(s.values, k)
                        for k in [
                            "competitor_listings",
                            "approved_product_attributes",
                            "classified_keywords",
                            "final_listing",
                            "final_st",
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    elif args.cmd == "review":
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        await graph.aupdate_state(
            {"configurable": {"thread_id": args.run_id}},
            {
                "approved_product_attributes": data,
                "status": "running",
                "pending_action": {},
            },
        )
        result = await graph.ainvoke(
            None, {"configurable": {"thread_id": args.run_id}}
        )
        print(f"Status: {result.get('status')}")

    elif args.cmd == "upload":
        config = {"configurable": {"thread_id": args.run_id}}
        with open(args.file, "rb") as f:
            content = f.read()

        if args.type == "keywords":
            data = json.loads(content)
            cleaned = toolbox.keyword.clean(data)
            await graph.aupdate_state(
                config,
                {"keyword_library": cleaned, "status": "running", "pending_action": {}},
            )
        elif args.type == "screenshot":
            save_path = (
                f"{toolbox.file_store.run_dir(args.run_id)}/{args.file.split('/')[-1]}"
            )
            with open(save_path, "wb") as out:
                out.write(content)
            s = graph.get_state(config)
            existing = s.values.get("rufus_screenshots", []) if s else []
            existing.append(save_path)
            await graph.aupdate_state(config, {"rufus_screenshots": existing})
        else:
            data = json.loads(content)
            await graph.aupdate_state(
                config,
                {
                    "competitor_listings": data,
                    "status": "running",
                    "pending_action": {},
                },
            )

        result = await graph.ainvoke(None, config)
        print(f"Status: {result.get('status')}")


if __name__ == "__main__":
    asyncio.run(main())
