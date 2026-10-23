"""Real Chromium, synthetic-only checks; no network or customer screenshots."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from utils.component_capture import ComponentCaptureError, capture_component_region


def main():
    def anchor(selector):
        return {'locator': selector, 'ancestor_levels': 0, 'count': 1}
    config = {'strategy': 'component_region', 'target': anchor('#image'),
              'edges': {'left': anchor('#tools'), 'bottom': anchor('#thumbnails')},
              'ready': {'visible': [anchor('#selected')], 'hidden': ['#loading']},
              'stable_ms': 400, 'sample_ms': 100}
    html = '''<style>body{margin:0} #viewer{position:absolute;left:50px;top:40px}
      canvas{width:800px;height:600px;background:black}
      #tools{position:absolute;left:10px;top:10px;width:90px;height:80px;background:red}
      #thumbnails{position:absolute;left:120px;top:500px;width:500px;height:60px;background:green}
      #selected{position:absolute;left:10px;top:10px} #loading{position:absolute;left:30px;top:30px}
      </style><div id=viewer><canvas id=image width=800 height=600></canvas>
      <div id=tools><span id=selected>selected</span></div><div id=thumbnails>thumbnails</div>
      <div id=loading>loading</div></div><script>
      const ctx=document.querySelector('canvas').getContext('2d');
      ctx.fillStyle='black';ctx.fillRect(0,0,800,600);ctx.fillStyle='orange';ctx.fillRect(250,50,350,400);
      setTimeout(()=>document.querySelector('#loading').remove(),300);
      </script>'''
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1200,'height':900}, device_scale_factor=1)
        page.set_content(html)
        _, evidence = capture_component_region(page, config, 4000)
        assert evidence['clip'] == {'x':150,'y':40,'width':700,'height':500}
        results['initial'] = evidence
        page.locator('#viewer').evaluate("e=>{e.style.left='100px';e.style.top='70px'}")
        _, moved = capture_component_region(page, config, 4000)
        assert moved['clip'] == {'x':200,'y':70,'width':700,'height':500}
        results['moved'] = moved
        page.locator('#image').evaluate("e=>{const c=e.getContext('2d');c.fillStyle='black';c.fillRect(0,0,800,600)}")
        try:
            capture_component_region(page, config, 1200)
        except ComponentCaptureError as exc:
            assert 'BLANK' in str(exc)
            results['blank_rejected'] = True
        else:
            raise AssertionError('Flat frame accepted')
        page.locator('#selected').evaluate('e=>e.remove()')
        try:
            capture_component_region(page, config, 1200)
        except ComponentCaptureError as exc:
            assert 'NOT_READY' in str(exc)
            results['missing_state_rejected'] = True
        else:
            raise AssertionError('Missing state accepted')
        browser.close()
    print(json.dumps(results))


if __name__ == '__main__':
    main()
