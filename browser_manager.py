"""
浏览器管理 — 启动前自动关闭残留进程
"""

import os
import time
import subprocess
import platform
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService


def get_browser_choice():
    print("\n可用浏览器：")
    print("  1. Google Chrome")
    print("  2. Microsoft Edge")
    choice = input("请选择 (1 或 2，默认 1): ").strip()
    if choice == "2":
        return "edge"
    return "chrome"


def create_driver(browser_type="auto"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if browser_type == "auto":
        chrome_path = os.path.join(base_dir, "chromedriver.exe")
        edge_path = os.path.join(base_dir, "msedgedriver.exe")
        if os.path.exists(chrome_path) and os.path.exists(edge_path):
            browser_type = get_browser_choice()
        elif os.path.exists(chrome_path):
            browser_type = "chrome"
        elif os.path.exists(edge_path):
            browser_type = "edge"
        else:
            print("未找到 WebDriver")
            return None
    if browser_type == "chrome":
        return _create_chrome(base_dir)
    elif browser_type == "edge":
        return _create_edge(base_dir)
    return None


def _kill_previous_sessions(browser_type):
    """关闭之前由本工具启动的浏览器残留进程"""
    profile_name = "edge_profile" if browser_type == "edge" else "chrome_profile"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_path = os.path.join(base_dir, profile_name)

    if platform.system() != "Windows":
        return

    process_name = "msedge.exe" if browser_type == "edge" else "chrome.exe"

    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='" + process_name + "'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        killed = 0
        for line in lines:
            if profile_name in line:
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    if pid.isdigit():
                        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
                        killed += 1
        if killed > 0:
            print("[browser] 关闭了 " + str(killed) + " 个残留 " + process_name + " 进程")
            time.sleep(2)
    except Exception as e:
        print("[browser] 清理残留进程: " + str(e))


def _maximize_safe(driver):
    try:
        driver.maximize_window()
        print("[browser] 窗口已最大化")
    except Exception:
        try:
            sw = driver.execute_script("return screen.availWidth")
            sh = driver.execute_script("return screen.availHeight")
            driver.set_window_size(sw, sh)
            print("[browser] 窗口已设为屏幕大小")
        except Exception:
            print("[browser] 窗口调整跳过")


def _create_chrome(base_dir):
    _kill_previous_sessions("chrome")
    profile_dir = os.path.join(base_dir, "chrome_profile")
    driver_path = os.path.join(base_dir, "chromedriver.exe")
    options = webdriver.ChromeOptions()
    options.add_argument("--user-data-dir=" + profile_dir)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    print("正在启动 Chrome...")
    try:
        if os.path.exists(driver_path):
            service = ChromeService(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
        print("Chrome 启动成功")
        _maximize_safe(driver)
        return driver
    except Exception as e:
        print("Chrome 启动失败: " + str(e))
        print("提示：请关闭所有 Chrome 窗口后重试，或在网页上重新点击「开始自动阅卷」")
        return None


def _create_edge(base_dir):
    _kill_previous_sessions("edge")
    profile_dir = os.path.join(base_dir, "edge_profile")
    driver_path = os.path.join(base_dir, "msedgedriver.exe")
    options = webdriver.EdgeOptions()
    options.add_argument("--user-data-dir=" + profile_dir)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    print("正在启动 Edge...")
    try:
        if os.path.exists(driver_path):
            service = EdgeService(executable_path=driver_path)
            driver = webdriver.Edge(service=service, options=options)
        else:
            driver = webdriver.Edge(options=options)
        print("Edge 启动成功")
        _maximize_safe(driver)
        return driver
    except Exception as e:
        print("Edge 启动失败: " + str(e))
        print("提示：请关闭所有 Edge 窗口后重试，或在网页上重新点击「开始自动阅卷」")
        return None
