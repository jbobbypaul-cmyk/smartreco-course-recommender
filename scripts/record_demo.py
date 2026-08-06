"""Record a SmartReco judge demo video with Playwright."""
from __future__ import annotations

import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT_DIR = Path(__file__).resolve().parents[1] / "demos"
VIDEO_DIR = OUT_DIR / "raw"


def overlay(page, text: str):
    page.evaluate(
        """(text) => {
          let el = document.getElementById('demo-overlay');
          if (!el) {
            el = document.createElement('div');
            el.id = 'demo-overlay';
            el.style.cssText = 'position:fixed;left:24px;bottom:24px;z-index:99999;background:#172033e6;color:#fff;padding:12px 16px;border-radius:12px;font:600 16px system-ui;max-width:70%;box-shadow:0 8px 30px #0005';
            document.body.appendChild(el);
          }
          el.textContent = text;
        }""",
        text,
    )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    demo_email = f"demo.judge.{stamp}@smartreco.test"
    demo_password = "DemoJudge123!"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()

        # 1. Landing
        page.goto(BASE, wait_until="networkidle")
        overlay(page, "1/6 SmartReco — behavioral AI course recommender")
        page.wait_for_timeout(2500)

        # 2. Register regular user
        overlay(page, "2/6 Create a learner account")
        page.locator("form[action='/register'] input[name='email']").fill(demo_email)
        page.locator("form[action='/register'] input[name='password']").fill(demo_password)
        page.locator("form[action='/register'] button").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)

        # 3. Search + browse
        overlay(page, "3/6 Track search + product exploration")
        if page.locator("#search-input").count():
            page.fill("#search-input", "agentic AI")
            page.locator("#search button").click()
            page.wait_for_timeout(1500)
        visible_btns = page.locator("[data-product-id]:not([hidden]) .view-product")
        count = min(visible_btns.count(), 3)
        if count == 0:
            # Clear filter if search hid everything, then browse catalog
            page.fill("#search-input", "")
            page.locator("#search button").click()
            page.wait_for_timeout(800)
            visible_btns = page.locator("[data-product-id]:not([hidden]) .view-product")
            count = min(visible_btns.count(), 3)
        for i in range(count):
            visible_btns.nth(i).click(force=True)
            page.wait_for_timeout(800)
        page.wait_for_timeout(1500)

        # Generate enough signal + force refresh via API (session cookie present)
        overlay(page, "4/6 Agent refreshes catalog-grounded recommendations")
        for _ in range(4):
            page.evaluate(
                """async () => {
                  const uuid = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
                    const r = Math.random() * 16 | 0;
                    const v = c === 'x' ? r : (r & 0x3 | 0x8);
                    return v.toString(16);
                  });
                  const events = [];
                  for (let i = 0; i < 8; i++) {
                    events.push({
                      event_id: uuid(),
                      event_type: i % 2 ? 'search' : 'product_click',
                      query: i % 2 ? 'agentic AI systems' : null,
                      product_id: 1,
                      occurred_at: new Date().toISOString(),
                      metadata: {demo: true}
                    });
                  }
                  await fetch('/api/events', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({events})});
                  await fetch('/api/recommendations/refresh', {method:'POST'});
                }"""
            )
            page.wait_for_timeout(1000)
        page.reload(wait_until="networkidle")
        overlay(page, "4/6 Personalized narrative + grounded course cards")
        page.wait_for_timeout(2500)
        if page.locator(".agent-trace").count():
            page.locator(".agent-trace summary").click()
            overlay(page, "4/6 LangGraph agent workflow trace (analyze → retrieve → rerank → generate)")
            page.wait_for_timeout(3000)

        # 5. Admin catalog / dual-write
        page.goto(f"{BASE}/logout", wait_until="networkidle")
        # logout is POST only — use form via login page flow
        page.goto(BASE, wait_until="networkidle")
        # ensure signed out
        if page.locator("form[action='/logout']").count():
            page.locator("form[action='/logout'] button").click()
            page.wait_for_load_state("networkidle")

        overlay(page, "5/6 Admin catalog with dual-write vector sync")
        page.locator("form[action='/login'] input[name='email']").fill("admin@smartreco.local")
        page.locator("form[action='/login'] input[name='password']").fill("ChangeMe123!")
        page.locator("form[action='/login'] button").click()
        page.wait_for_load_state("networkidle")
        page.goto(f"{BASE}/admin", wait_until="networkidle")
        overlay(page, "5/6 Products synced to SQL + Chroma (Mesh embeddings)")
        page.wait_for_timeout(3500)
        page.evaluate("window.scrollTo(0, 400)")
        page.wait_for_timeout(2000)

        # 6. SMTP digest panel
        page.evaluate("window.scrollTo(0, 0)")
        overlay(page, "6/6 Bonus: scheduled SendGrid digest + LangSmith-ready tracing")
        page.wait_for_timeout(3500)

        overlay(page, "SmartReco demo complete — ready for judges")
        page.wait_for_timeout(2500)

        video_path = Path(page.video.path()) if page.video else None
        context.close()
        browser.close()

    if not video_path or not video_path.exists():
        # Playwright writes video after context close; find newest
        vids = sorted(VIDEO_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not vids:
            raise SystemExit("No demo video recorded")
        video_path = vids[0]

    final_webm = OUT_DIR / "smartreco-judge-demo.webm"
    final_mp4 = OUT_DIR / "smartreco-judge-demo.mp4"
    final_webm.write_bytes(video_path.read_bytes())
    print(f"webm={final_webm}")
    print(f"raw={video_path}")
    print(f"mp4_target={final_mp4}")


if __name__ == "__main__":
    main()
