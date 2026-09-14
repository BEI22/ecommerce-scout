#!/usr/bin/env python3
"""登录淘宝 — 扫码一次，保存会话，后续自动复用"""

import asyncio, sys
if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

sys.path.insert(0, '.')
from src.scrapers.base import BaseScraper
from src.config import CRAWLER, CACHE_DIR
from pathlib import Path
import json

class LoginHelper(BaseScraper):
    """临时爬虫，只用于登录"""
    platform = None  # will be set per platform
    async def search(self, keyword, max_pages=None): pass  # not used


async def login_platform(name, login_url, platform_str):
    print(f"\n{'='*60}")
    print(f"  登录 {name}")
    print(f"{'='*60}")
    print(f"  即将打开 {name} 登录页面...")
    print(f"  请在浏览器中扫码/输入账号密码登录")
    print(f"  登录成功后，回来这里按 Enter")
    print(f"{'='*60}")

    helper = LoginHelper()
    helper.platform = type('Platform', (), {'value': platform_str})()

    try:
        CRAWLER["headless"] = False
        await helper._launch_browser()
        context = await helper._new_context()
        helper._context = context
        page = await context.new_page()

        # 打开登录页
        await page.goto(login_url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # 等用户登录
        input("\n>>> 登录完成后按 Enter 继续...")

        # 立即保存会话！
        state = await context.storage_state()
        session_file = CACHE_DIR / f"{platform_str}_session.json"
        session_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ 会话已保存到: {session_file}")

        # 验证一下
        verify_urls = {
            "taobao": "https://s.taobao.com/search?q=test",
            "pinduoduo": "https://mobile.yangkeduo.com/search_result.html?search_key=test",
        }
        await page.goto(verify_urls.get(platform_str, login_url), timeout=15000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        title = await page.title()
        print(f"  验证页面: {title[:40]}")

        await page.close()
        await context.close()
    except Exception as e:
        print(f"  ⚠ 出错: {e}")
    finally:
        await helper.close()

    print(f"  {name} 登录流程完成！\n")


async def main():
    print("""
  ╔════════════════════════════════════════╗
  ║     TAgent 登录助手                     ║
  ║     扫码一次，后续自动复用               ║
  ╚════════════════════════════════════════╝
    """)

    choice = input("登录哪个? [1] 淘宝 [2] 拼多多 [3] 两个都登: ").strip()

    if choice in ("1", "3"):
        await login_platform(
            "淘宝",
            "https://login.taobao.com/member/login.jhtml",
            "taobao"
        )

    if choice in ("2", "3"):
        await login_platform(
            "拼多多",
            "https://mobile.yangkeduo.com/login.html",
            "pinduoduo"
        )

    print("✅ 完成！现在可以真实搜索了:")
    print("   python unified_cli.py scout '露营灯'")
    print("   python unified_cli.py scout '手机壳' -p taobao -n 2")


if __name__ == "__main__":
    asyncio.run(main())
