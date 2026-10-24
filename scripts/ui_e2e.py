"""Сквозной UI-тест (Playwright): python scripts/ui_e2e.py [http://localhost:8080/]
   pip install playwright && playwright install chromium; сервер должен быть запущен."""
import asyncio, sys
from playwright.async_api import async_playwright
BASE=sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8080/'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width':1440,'height':900}); pg = await ctx.new_page()
        errs=[]; pg.on('pageerror', lambda e: errs.append('PAGEERR '+str(e))); pg.on('console', lambda m: errs.append('CONSOLE '+m.text) if m.type=='error' else None)
        pg.on('response', lambda r: errs.append(f'HTTP {r.status} {r.url}') if r.status>=400 and '/api/' in r.url else None)
        step=lambda s: print('•',s)
        await pg.goto(BASE); await pg.click('button[type=submit]'); await pg.wait_for_selector('.entry-banner')
        step('login ok')
        # смена пользователя через меню аватара
        await pg.click('.avatar-button'); await pg.wait_for_selector('.user-dropdown .dropdown-row')
        n=await pg.locator('.user-dropdown .dropdown-row').count(); step(f'user menu rows {n}')
        await pg.click('.user-dropdown .dropdown-row >> text=Ирина Волкова'); await pg.wait_for_selector('.toast'); await pg.wait_for_timeout(1000)
        name=await pg.inner_text('.avatar-copy b'); step('now: '+name)
        assert 'Волкова' in name
        comps=await pg.locator('.select-button').inner_text(); step('company '+comps.split('\n')[0])
        await pg.click('.select-button'); k=await pg.locator('.company-dropdown .dropdown-row').count(); step(f'companies for CFO: {k}'); assert k==2
        await pg.click('.company-dropdown .dropdown-row >> nth=1'); await pg.wait_for_timeout(800)
        # click-away и Escape
        await pg.click('.role-button'); assert await pg.locator('.role-dropdown').count()==1
        await pg.mouse.click(700,500); await pg.wait_for_timeout(200); assert await pg.locator('.role-dropdown').count()==0; step('click-away closes menu')
        await pg.click('.avatar-button'); await pg.keyboard.press('Escape'); await pg.wait_for_timeout(200); assert await pg.locator('.user-dropdown').count()==0; step('Escape closes menu')
        # выход
        await pg.click('.avatar-button'); await pg.click('.logout-row'); await pg.wait_for_selector('.login-card'); step('logout ok')
        await pg.reload(); await pg.wait_for_selector('.login-card'); step('after reload: login page (no stale session)')
        # быстрый вход под другой ролью с экрана входа
        await pg.click('.login-accounts button >> nth=3'); await pg.wait_for_selector('.entry-banner'); step('quick login from login screen: '+await pg.inner_text('.avatar-copy b'))
        # лента, фильтры, разбор, вопросы, источник, действия, обратная связь
        await pg.click('.nav-item.featured'); await pg.wait_for_selector('.feed-card')
        for t in ['Риски','Возможности','События','Аналитика банка','Все события']:
            await pg.click(f'.filter-tabs button:has-text("{t}")'); await pg.wait_for_timeout(150)
        step('tabs ok')
        await pg.click('.feed-card >> nth=0'); await pg.wait_for_selector('.detail-drawer .sec')
        await pg.click('.detail-drawer .btn.small:has-text("первоисточник")'); await pg.wait_for_selector('.modal .src-text'); step('source modal ok'); await pg.keyboard.press('Escape')
        await pg.wait_for_timeout(200)
        await pg.click('.detail-drawer .q-chips button >> nth=0'); await pg.wait_for_selector('.detail-drawer .assistant-answer'); step('drawer Q&A ok')
        await pg.click('.btn:has-text("Связаться с менеджером")'); await pg.wait_for_selector('.toast'); step('action: '+await pg.inner_text('.toast'))
        await pg.click('button[aria-label="Полезно"]'); await pg.wait_for_timeout(300)
        await pg.click('.drawer-footer >> text=Вернуться в ленту'); await pg.wait_for_timeout(200)
        assert await pg.locator('.detail-drawer').count()==0
        # своя новость
        await pg.click('text=Проверить свою новость'); await pg.click('.modal .btn.primary'); await pg.wait_for_selector('.modal .chip.ok'); await pg.click('text=Показать анализ для этой компании'); await pg.wait_for_selector('.detail-drawer .sec'); step('own news ok'); await pg.keyboard.press('Escape')
        # аналитика, источник из KPI
        await pg.click('.nav-item >> text=Аналитика банка'); await pg.wait_for_selector('.kpi'); await pg.click('.kpi >> nth=0'); await pg.wait_for_selector('.modal .pdf-frame'); await pg.click('.src-tabs button >> text=Текст страницы'); await pg.wait_for_selector('.modal .src-text'); step('analytics source ok'); await pg.keyboard.press('Escape')
        await pg.click('.notification'); await pg.wait_for_selector('.bell-dropdown'); await pg.click('.bell-actions >> text=Открыть ленту'); await pg.wait_for_selector('.feed-card'); step('bell dropdown -> feed ok')
        # узкие экраны
        for w,h in [(1000,800),(390,800)]:
            await pg.set_viewport_size({'width':w,'height':h}); await pg.wait_for_timeout(300)
            await pg.click('.avatar-button'); vis=await pg.locator('.user-dropdown').is_visible()
            box=await pg.locator('.user-dropdown').bounding_box(); step(f'{w}px user menu visible={vis} box={box and (round(box["x"]),round(box["width"]))}')
            assert box['x']>=0
            await pg.keyboard.press('Escape')
            ov=await pg.evaluate('document.documentElement.scrollWidth - window.innerWidth'); step(f'{w}px horizontal overflow={ov}')
        print('ERRORS:', errs); await b.close()
        assert not errs, errs
        print('OK')
asyncio.run(main())
