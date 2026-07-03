from playwright.sync_api import sync_playwright
import time

def check_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})

        # 访问本地页面
        page.goto('http://127.0.0.1:8000/')

        # 等待页面加载
        time.sleep(2)

        # 截图
        page.screenshot(path='screenshot.png', full_page=True)

        # 获取 hero 区域的尺寸信息
        hero_box = page.locator('.hero').bounding_box()
        hero_inner_box = page.locator('.hero-inner').bounding_box()

        print("Hero 区域信息:")
        print(f"  位置: x={hero_box['x']}, y={hero_box['y']}")
        print(f"  尺寸: width={hero_box['width']}, height={hero_box['height']}")
        print()
        print("Hero-inner 区域信息:")
        print(f"  位置: x={hero_inner_box['x']}, y={hero_inner_box['y']}")
        print(f"  尺寸: width={hero_inner_box['width']}, height={hero_inner_box['height']}")
        print()
        print("截图已保存到 screenshot.png")

        browser.close()

if __name__ == '__main__':
    check_page()
