"""
元素定位器 — iframe 上下文管理 + 去重检测 + 使用前重新定位
"""

import time
from selenium.webdriver.common.by import By


class ElementFinder:
    def __init__(self, driver):
        self.driver = driver
        self.score_mode = "none"
        self.in_iframe = False
        self.iframe_index = -1

    def _switch_to_context(self):
        """切换到元素所在的 iframe 上下文"""
        self.driver.switch_to.default_content()
        if self.in_iframe and self.iframe_index >= 0:
            try:
                self.driver.switch_to.frame(self.iframe_index)
            except Exception:
                self.driver.switch_to.default_content()
                self.in_iframe = False
                self.iframe_index = -1

    def _find_score_buttons_in_context(self, context):
        """在当前上下文中查找数字评分按钮（精确匹配 + 去重）"""
        found = {}
        for tag in ["button", "span", "div", "a", "li", "td", "p"]:
            try:
                elements = context.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        txt = el.text.strip()
                        if not txt.isdigit():
                            continue
                        num = int(txt)
                        if num > 15:
                            continue
                        if not el.is_displayed():
                            continue
                        loc = el.size
                        if loc["width"] < 8 or loc["width"] > 150:
                            continue
                        if loc["height"] < 8 or loc["height"] > 150:
                            continue
                        # 精确匹配：innerText 必须完全等于数字
                        inner = el.get_attribute("innerText").strip()
                        if inner != txt:
                            continue
                        # 保留每个数字的第一个匹配
                        if num not in found:
                            found[num] = el
                    except Exception:
                        continue
            except Exception:
                continue

        if found:
            buttons = [found[k] for k in sorted(found.keys())]
            nums = [str(k) for k in sorted(found.keys())]
            print("[定位] 数字按钮: " + str(nums))
            return buttons
        return []

    def auto_detect_score_input(self):
        self.score_mode = "none"
        self.in_iframe = False
        self.iframe_index = -1

        self.driver.switch_to.default_content()

        # 主页面：先找数字按钮
        btns = self._find_score_buttons_in_context(self.driver)
        if btns and len(btns) >= 2:
            self.score_mode = "buttons"
            print("[定位] 主页面找到数字按钮")
            return

        # 主页面：找输入框
        if self._find_input_in_context(self.driver, -1):
            return

        # iframe 中查找
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        print("[定位] 检测到 " + str(len(iframes)) + " 个 iframe")
        for i in range(len(iframes)):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(i)
            except Exception:
                continue

            btns = self._find_score_buttons_in_context(self.driver)
            if btns and len(btns) >= 2:
                self.score_mode = "buttons"
                self.in_iframe = True
                self.iframe_index = i
                print("[定位] iframe " + str(i) + " 找到数字按钮")
                return

            if self._find_input_in_context(self.driver, i):
                return

            self.driver.switch_to.default_content()

        self.driver.switch_to.default_content()
        print("[定位] 未找到评分元素")

    def _find_input_in_context(self, context, iframe_idx):
        selectors = [
            "input[type='number']",
            "input[name*='score']",
            "input[name*='grade']",
            "input[placeholder*='分']",
            "input[placeholder*='请输入']",
            "[class*='score'] input",
            "[class*='grade'] input",
            "input[type='text']",
        ]
        for sel in selectors:
            try:
                elements = context.find_elements(By.CSS_SELECTOR, sel)
                for el in elements:
                    if el.is_displayed():
                        self.score_mode = "input"
                        if iframe_idx >= 0:
                            self.in_iframe = True
                            self.iframe_index = iframe_idx
                        print("[定位] 找到输入框: " + sel + (" (iframe " + str(iframe_idx) + ")" if iframe_idx >= 0 else ""))
                        return True
            except Exception:
                continue
        return False

    def auto_detect_submit_button(self):
        self.driver.switch_to.default_content()
        keywords = ["确认作答", "提交分数", "确认评分", "确认", "下一题", "下一", "提交", "保存", "确定"]

        # 主页面查找
        if self._find_submit_in_context(keywords, -1):
            return

        # iframe 中查找
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(len(iframes)):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(i)
                if self._find_submit_in_context(keywords, i):
                    return
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass

        self.driver.switch_to.default_content()
        print("[定位] 未找到提交按钮")

    def _find_submit_in_context(self, keywords, iframe_idx):
        for tag in ["button", "a", "div", "span", "input"]:
            try:
                elements = self.driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        txt = el.text.strip()
                        if txt and any(k in txt for k in keywords) and el.is_displayed():
                            if iframe_idx >= 0:
                                self.in_iframe = True
                                self.iframe_index = iframe_idx
                            where = "iframe " + str(iframe_idx) if iframe_idx >= 0 else "主页面"
                            print("[定位] 找到提交按钮: " + txt + " (" + where + ")")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def _find_and_fill_score(self, driver, score_str):
        """在当前上下文中重新查找数字按钮并点击"""
        btns = self._find_score_buttons_in_context(driver)
        for btn in btns:
            try:
                if btn.text.strip() == score_str and btn.is_displayed():
                    btn.click()
                    print("[填分] 点击按钮: " + score_str)
                    return True
            except Exception:
                continue
        return False

    def _find_and_click_submit(self, driver):
        """在当前上下文中重新查找提交按钮并点击"""
        keywords = ["确认作答", "提交分数", "确认评分", "确认", "下一题", "下一", "提交", "保存", "确定"]
        for tag in ["button", "a", "div", "span"]:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        txt = el.text.strip()
                        if txt and any(k in txt for k in keywords) and el.is_displayed():
                            el.click()
                            print("[提交] 点击: " + txt)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def fill_score(self, driver, score):
        """填入分数"""
        score_str = str(int(float(score)))

        self._switch_to_context()

        if self.score_mode == "buttons":
            # 重新查找按钮并点击
            if self._find_and_fill_score(driver, score_str):
                return True
            print("[填分] 按钮 " + score_str + " 不可用，尝试自定义输入")
            return self._try_custom_input(driver, score_str)

        if self.score_mode == "input":
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR,
                    "input[placeholder*='分'], input[type='number'], input[type='text'], input[name*='score']")
                for inp in inputs:
                    if inp.is_displayed():
                        inp.click()
                        time.sleep(0.3)
                        inp.clear()
                        time.sleep(0.1)
                        driver.execute_script(
                            "arguments[0].value = arguments[1];"
                            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                            "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                            inp, score_str,
                        )
                        print("[填分] 输入框填入: " + score_str)
                        return True
            except Exception as e:
                print("[填分] 输入失败: " + str(e))

        print("[填分] 无可用方式")
        return False

    def _try_custom_input(self, driver, score_str):
        try:
            all_elements = driver.find_elements(By.XPATH, "//*[contains(text(),'自定义')]")
            for el in all_elements:
                if el.is_displayed():
                    el.click()
                    print("[填分] 点击「自定义」")
                    time.sleep(1)
                    inputs = driver.find_elements(By.CSS_SELECTOR,
                        "input[type='text'], input[type='number'], input:not([type]):not([hidden])")
                    for inp in inputs:
                        if inp.is_displayed():
                            inp.click()
                            time.sleep(0.2)
                            inp.clear()
                            inp.send_keys(score_str)
                            print("[填分] 自定义输入: " + score_str)
                            time.sleep(0.3)
                            for btn in driver.find_elements(By.TAG_NAME, "button"):
                                if any(k in btn.text for k in ["确认", "确定"]):
                                    btn.click()
                                    return True
                            return True
        except Exception as e:
            print("[填分] 自定义失败: " + str(e))
        return False

    def click_submit(self, driver):
        """点击提交按钮 — 每次重新查找"""
        self._switch_to_context()

        if self._find_and_click_submit(driver):
            return True

        # 备选：尝试 JS 点击
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in btns:
                try:
                    txt = btn.text.strip()
                    if any(k in txt for k in ["提交", "确认", "下一"]):
                        driver.execute_script("arguments[0].click();", btn)
                        print("[提交] JS点击: " + txt)
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        print("[提交] 失败")
        return False

    def re_detect(self):
        self.auto_detect_score_input()
        self.auto_detect_submit_button()
