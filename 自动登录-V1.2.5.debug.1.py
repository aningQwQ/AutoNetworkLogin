"""
AutoNetworkLogin Debug 版本
============================
基于原始版本 V1.2.5 添加详细日志记录，用于诊断 ExplorerPatcher 崩溃问题

日志功能：
1. 记录所有操作到 debug_log.txt
2. 精确时间戳（毫秒级）
3. 分类日志（APP/LOGIN/MONITOR/NETWORK）
4. 实时显示在窗口中

使用方法：
1. 运行程序
2. 当认证服务器重启导致断开时，观察日志
3. 崩溃发生后，查看 debug_log.txt 分析原因
"""

import sys
import os
import time
import datetime
import threading
import requests
import traceback
import socket
import yaml
from PyQt6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QMainWindow, 
                            QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QTextEdit, QLabel, QCheckBox, QSpinBox, QMessageBox)
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, Qt


class DebugLogger:
    """调试日志记录器"""
    
    def __init__(self, log_file="debug_log.txt"):
        self.log_file = log_file
        self.running = True
        self.log_queue = []
        self.queue_lock = threading.Lock()
        self.start_time = time.time()
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 清空旧日志
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"{'='*80}\n")
            f.write(f"AutoNetworkLogin Debug 日志\n")
            f.write(f"会话ID: {self.session_id}\n")
            f.write(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\n")
            f.write(f"{'='*80}\n\n")
        
        # 启动日志写入线程
        self.write_thread = threading.Thread(target=self._write_loop, daemon=True)
        self.write_thread.start()
    
    def log(self, level, category, message, detail=""):
        """记录日志"""
        if not self.running:
            return
        
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        elapsed = time.time() - self.start_time
        elapsed_str = f"{elapsed:8.3f}s"
        
        # 确保 detail 是字符串
        if detail is not None and not isinstance(detail, str):
            detail = str(detail)
        
        # 格式化为字符串
        log_str = f"[{timestamp}] [+{elapsed_str}] [{level}] [{category}] {message}"
        if detail:
            log_str += f"\n    详情: {detail}"
        
        # 添加到队列
        with self.queue_lock:
            self.log_queue.append(log_str)
        
        return log_str
    
    def _write_loop(self):
        """日志写入循环"""
        while self.running:
            try:
                with self.queue_lock:
                    if self.log_queue:
                        logs_to_write = self.log_queue[:100]
                        self.log_queue = self.log_queue[100:]
                    else:
                        logs_to_write = None
                
                if logs_to_write:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        for log_str in logs_to_write:
                            f.write(log_str + '\n')
                            f.flush()
                
                time.sleep(0.1)
                
            except Exception as e:
                print(f"日志写入错误: {e}")
                time.sleep(1)
    
    def close(self):
        """关闭日志记录器"""
        self.running = False
        
        # 写入剩余日志
        with self.queue_lock:
            remaining = self.log_queue.copy()
        
        if remaining:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"日志会话结束: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\n")
                f.write(f"{'='*80}\n")
                for log_str in remaining:
                    f.write(log_str + '\n')
        
        print(f"日志已保存到: {os.path.abspath(self.log_file)}")
    
    # 便捷方法
    def info(self, category, message, detail=""):
        return self.log("INFO", category, message, detail)
    
    def debug(self, category, message, detail=""):
        return self.log("DEBUG", category, message, detail)
    
    def warning(self, category, message, detail=""):
        return self.log("WARN", category, message, detail)
    
    def error(self, category, message, detail=""):
        return self.log("ERROR", category, message, detail)
    
    def critical(self, category, message, detail=""):
        return self.log("CRIT", category, message, detail)


class LoginWorker(QObject):
    """登录工作线程 - Debug版本"""
    login_result = pyqtSignal(str, bool)  # message, success
    
    def __init__(self, config, logger):
        super().__init__()
        self.config = config
        self.logger = logger
        self.login_count = 0
    
    def do_login(self):
        """执行登录操作"""
        self.login_count += 1
        thread_id = threading.current_thread().ident
        
        self.logger.info("LOGIN", f"登录尝试 #{self.login_count}", 
                        f"线程ID: {thread_id}")
        
        start_time = time.time()
        
        try:
            login_url = self.config['Login']['url']
            login_data = self.get_login_data()
            headers = self.get_headers()
            
            # DNS解析
            try:
                from urllib.parse import urlparse
                parsed = urlparse(login_url)
                hostname = parsed.netloc
                ip = socket.gethostbyname(hostname)
                self.logger.info("LOGIN", "DNS解析", f"{hostname} -> {ip}")
            except Exception as e:
                self.logger.warning("LOGIN", "DNS解析失败", str(e))
            
            self.logger.debug("LOGIN", "发送登录请求", 
                            f"URL: {login_url}")
            
            # 发送请求
            request_start = time.time()
            response = requests.post(
                login_url,
                data=login_data,
                headers=headers,
                timeout=10
            )
            request_time = time.time() - request_start
            
            self.logger.info("LOGIN", "收到响应",
                            f"状态码: {response.status_code}, 耗时: {request_time:.3f}s")
            
            # 尝试解析响应
            try:
                result = response.json()
                self.logger.debug("LOGIN", "JSON解析结果", str(result))
                
                if result.get('success'):
                    msg = f"登录成功: {result.get('msg', '')}"
                    self.logger.info("LOGIN", "登录成功", msg)
                    self.login_result.emit(msg, True)
                else:
                    msg = f"登录失败: {result.get('msg', '未知错误')}"
                    self.logger.warning("LOGIN", "登录失败", msg)
                    self.login_result.emit(msg, False)
                    
            except ValueError:
                if 'success' in response.text.lower() or 'logon success' in response.text.lower():
                    msg = "登录成功"
                    self.logger.info("LOGIN", "登录成功(文本匹配)", msg)
                    self.login_result.emit(msg, True)
                else:
                    msg = f"登录响应: {response.text[:100]}"
                    self.logger.warning("LOGIN", "登录响应异常", msg)
                    self.login_result.emit(msg, False)
                
        except requests.exceptions.ConnectionError as e:
            error_msg = f"连接失败: {str(e)}"
            self.logger.error("LOGIN", "连接错误", error_msg)
            self.login_result.emit(error_msg, False)
            
        except requests.exceptions.Timeout as e:
            error_msg = f"连接超时: {str(e)}"
            self.logger.error("LOGIN", "超时错误", error_msg)
            self.login_result.emit(error_msg, False)
            
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            self.logger.error("LOGIN", "异常", error_msg, traceback.format_exc())
            self.login_result.emit(error_msg, False)
        
        total_time = time.time() - start_time
        self.logger.info("LOGIN", f"登录流程结束", f"总耗时: {total_time:.3f}s")
    
    def get_login_data(self):
        """从配置获取登录数据"""
        data = {
            "opr": self.config['Login']['opr'],
            "userName": self.config['Login']['userName'],
            "pwd": "***",  # 不记录密码
            "auth_tag": self.config['Login']['auth_tag'],
            "rememberPwd": self.config['Login']['rememberPwd']
        }
        return data
    
    def get_headers(self):
        """从配置获取请求头"""
        return self.config['Headers']


class NetworkMonitor(QObject):
    """网络监控器 - Debug版本"""
    network_status = pyqtSignal(bool)  # status
    
    def __init__(self, config, logger):
        super().__init__()
        self.config = config
        self.logger = logger
        self.running = True
        self.check_count = 0
        self.consecutive_failures = 0
        self.prev_status = None
        
        self.logger.info("MONITOR", "网络监控器初始化", 
                        f"检查间隔: {self.config['Settings'].get('check_interval', 60)}s")
    
    def stop(self):
        """停止监控"""
        self.logger.info("MONITOR", "停止网络监控")
        self.running = False
    
    def run(self):
        """运行网络监控"""
        self.logger.info("MONITOR", "开始监控循环")
        
        while self.running:
            check_start = time.time()
            self.check_count += 1
            
            try:
                test_url = self.config['Settings'].get('test_url', 'http://www.baidu.com')
                test_timeout = self.config['Settings'].get('test_timeout', 5)
                
                # 获取本地IP
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                except:
                    local_ip = "N/A"
                
                self.logger.debug("MONITOR", f"检查 #{self.check_count}", 
                                f"本地IP: {local_ip}, 测试URL: {test_url}")
                
                # 发送测试请求
                response = requests.get(test_url, timeout=test_timeout)
                is_connected = response.status_code == 200
                
                # 状态变化检测
                if self.prev_status is None:
                    self.logger.info("MONITOR", "首次检查", 
                                    f"网络{'正常' if is_connected else '断开'}")
                elif self.prev_status != is_connected:
                    change_type = "恢复" if is_connected else "断开"
                    self.logger.warning("MONITOR", f"网络状态变化: {change_type}",
                                       f"之前: {'正常' if self.prev_status else '断开'}, "
                                       f"现在: {'正常' if is_connected else '断开'}")
                else:
                    self.logger.debug("MONITOR", "网络状态无变化",
                                     f"连续{self.consecutive_failures + 1 if not is_connected else 1}次"
                                     f"{'失败' if not is_connected else '正常'}")
                
                # 更新失败计数
                if not is_connected:
                    self.consecutive_failures += 1
                else:
                    self.consecutive_failures = 0
                
                # 发送状态信号
                self.network_status.emit(is_connected)
                self.prev_status = is_connected
                
            except requests.exceptions.ConnectionError as e:
                self.consecutive_failures += 1
                self.logger.warning("MONITOR", f"连接失败 #{self.consecutive_failures}", 
                                   f"错误: {str(e)}")
                self.network_status.emit(False)
                
            except requests.exceptions.Timeout as e:
                self.consecutive_failures += 1
                self.logger.warning("MONITOR", f"超时 #{self.consecutive_failures}", 
                                   f"错误: {str(e)}")
                self.network_status.emit(False)
                
            except Exception as e:
                self.consecutive_failures += 1
                self.logger.error("MONITOR", f"异常 #{self.consecutive_failures}", 
                                 str(e), traceback.format_exc())
                self.network_status.emit(False)
            
            # 等待下一次检查
            check_interval = self.config['Settings'].get('check_interval', 60)
            elapsed = time.time() - check_start
            sleep_time = max(0, check_interval - elapsed)
            
            self.logger.debug("MONITOR", "检查完成",
                             f"耗时: {elapsed:.3f}s, 等待: {sleep_time:.3f}s")
            
            time.sleep(sleep_time)


class NetworkLoginApp(QMainWindow):
    """主窗口 - Debug版本"""
    
    def __init__(self):
        super().__init__()
        
        # 初始化日志记录器（最先）
        self.logger = DebugLogger("debug_log.txt")
        self.logger.info("APP", "程序启动", 
                        f"工作目录: {os.getcwd()}")
        
        self.config_file = "network_config.yaml"
        self.template_file = "network_config_template.yaml"
        self.config = {}
        
        self.logger.info("APP", "加载配置")
        self.load_or_create_config()
        
        # 初始化设置
        self.auto_reconnect = self.config['Settings'].get('auto_reconnect', True)
        self.check_interval = self.config['Settings'].get('check_interval', 60)
        self.periodic_login_interval = self.config['Settings'].get('periodic_login_interval', 0)
        self.forced_auto_reconnect = self.config['Settings'].get('forced_auto_reconnect', False)
        
        if self.forced_auto_reconnect:
            self.auto_reconnect = True
        
        self.logger.info("APP", "设置初始化",
                        f"自动重连: {self.auto_reconnect}, 检查间隔: {self.check_interval}s")
        
        # 初始化UI
        self.logger.info("APP", "初始化UI")
        self.init_ui()
        
        # 创建系统托盘
        self.logger.info("APP", "创建系统托盘")
        self.create_system_tray()
        
        # 启动网络监控
        self.logger.info("APP", "启动网络监控")
        self.start_network_monitor()
        
        # 启动定期登录定时器
        self.logger.info("APP", "启动定期登录")
        self.start_periodic_login_timer()
        
        # 更新状态显示
        self.update_status_display()
        
        # 配置文件监控
        self.config_last_modified = os.path.getmtime(self.config_file)
        self.config_monitor_timer = QTimer()
        self.config_monitor_timer.timeout.connect(self.check_config_update)
        self.config_monitor_timer.start(2000)
        
        # 日志刷新定时器
        self.log_flush_timer = QTimer()
        self.log_flush_timer.timeout.connect(self.flush_logs)
        self.log_flush_timer.start(500)
        
        self.logger.info("APP", "初始化完成", "所有组件已启动")
    
    def create_template_config(self):
        """创建带注释的配置模板文件"""
        template_content = '''# 网络登录工具配置文件模板
# Debug版本配置

# 登录配置部分
Login:
  url: "http://YOUR_LOGIN_SERVER_URL/ac_portal/login.php"
  opr: "pwdLogin"
  userName: "YOUR_USERNAME"
  pwd: "YOUR_PASSWORD"
  auth_tag: "TIMESTAMP"
  rememberPwd: "0"

# 请求头配置
Headers:
  Accept: "*/*"
  Accept-Encoding: "gzip, deflate"
  Accept-Language: "zh-CN,zh;q=0.9,en;q=0.8"
  Cache-Control: "no-cache"
  Connection: "keep-alive"
  Content-Type: "application/x-www-form-urlencoded; charset=UTF-8"
  Cookie: "YOUR_ACTUAL_COOKIE"
  DNT: "1"
  Host: "YOUR_LOGIN_SERVER_HOST"
  Origin: "http://YOUR_LOGIN_SERVER_HOST"
  Pragma: "no-cache"
  Referer: "YOUR_LOGIN_PAGE_URL"
  User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
  X-Requested-With: "XMLHttpRequest"

# 程序运行设置
Settings:
  auto_reconnect: true
  check_interval: 60
  test_url: "http://www.baidu.com"
  test_timeout: 5
  periodic_login_interval: 0
  forced_auto_reconnect: false
'''
        
        with open(self.template_file, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        self.logger.info("CONFIG", f"已创建配置模板: {self.template_file}")
    
    def create_default_config(self):
        """从模板文件创建默认的用户配置文件"""
        try:
            with open(self.template_file, 'r', encoding='utf-8') as f:
                template_config = yaml.safe_load(f)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(template_config, f, default_flow_style=False, 
                         allow_unicode=True, indent=2)
            
            self.logger.info("CONFIG", f"已创建默认配置: {self.config_file}")
            
        except Exception as e:
            self.logger.error("CONFIG", "创建默认配置失败", str(e))
    
    def load_or_create_config(self):
        """加载或创建配置文件"""
        self.logger.info("CONFIG", f"检查配置文件: {self.config_file}")
        
        if not os.path.exists(self.config_file):
            self.logger.info("CONFIG", "配置文件不存在，创建中")
            self.create_template_config()
            self.create_default_config()
        
        if not os.path.exists(self.template_file):
            self.create_template_config()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            self.logger.info("CONFIG", "配置加载成功")
        except Exception as e:
            self.logger.error("CONFIG", f"配置加载失败: {e}", traceback.format_exc())
            self.config = {}
    
    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, 
                         allow_unicode=True, indent=2)
            self.logger.info("CONFIG", "配置已保存")
        except Exception as e:
            self.logger.error("CONFIG", f"配置保存失败: {e}", traceback.format_exc())
    
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("AutoNetworkLogin Debug")
        self.setGeometry(100, 100, 600, 500)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # 标题
        title_label = QLabel("AutoNetworkLogin Debug 版本")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: blue;")
        layout.addWidget(title_label)
        
        info_label = QLabel(f"日志文件: {os.path.abspath('debug_log.txt')}")
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(info_label)
        
        # 状态显示
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 正在初始化...")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # 控制按钮
        button_layout = QHBoxLayout()
        
        self.login_btn = QPushButton("立即登录")
        self.login_btn.clicked.connect(self.manual_login)
        button_layout.addWidget(self.login_btn)
        
        self.auto_reconnect_cb = QCheckBox("自动重连")
        self.auto_reconnect_cb.setChecked(self.auto_reconnect)
        self.auto_reconnect_cb.stateChanged.connect(self.toggle_auto_reconnect)
        
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setEnabled(False)
            self.auto_reconnect_cb.setToolTip("强制自动重连已开启")
        
        button_layout.addWidget(self.auto_reconnect_cb)
        layout.addLayout(button_layout)
        
        # 配置管理按钮
        config_button_layout = QHBoxLayout()
        
        self.edit_config_btn = QPushButton("编辑配置")
        self.edit_config_btn.clicked.connect(self.edit_config)
        config_button_layout.addWidget(self.edit_config_btn)
        
        self.reload_config_btn = QPushButton("重新加载配置")
        self.reload_config_btn.clicked.connect(self.reload_config)
        config_button_layout.addWidget(self.reload_config_btn)
        
        self.hot_reload_cb = QCheckBox("自动热更新配置")
        self.hot_reload_cb.setChecked(True)
        self.hot_reload_cb.stateChanged.connect(self.toggle_hot_reload)
        config_button_layout.addWidget(self.hot_reload_cb)
        
        layout.addLayout(config_button_layout)
        
        # 检查间隔设置
        interval_layout = QVBoxLayout()
        
        network_check_layout = QHBoxLayout()
        network_check_layout.addWidget(QLabel("网络检查间隔(秒):"))
        
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 3600)
        self.interval_spin.setValue(self.check_interval)
        self.interval_spin.valueChanged.connect(self.update_check_interval)
        network_check_layout.addWidget(self.interval_spin)
        network_check_layout.addStretch()
        interval_layout.addLayout(network_check_layout)
        
        # 定期登录间隔
        periodic_login_layout = QHBoxLayout()
        periodic_login_layout.addWidget(QLabel("定期登录间隔(秒):"))
        
        self.periodic_interval_spin = QSpinBox()
        self.periodic_interval_spin.setRange(0, 86400)
        self.periodic_interval_spin.setValue(self.periodic_login_interval)
        self.periodic_interval_spin.setSpecialValueText("关闭")
        self.periodic_interval_spin.valueChanged.connect(self.update_periodic_login_interval)
        periodic_login_layout.addWidget(self.periodic_interval_spin)
        
        self.next_periodic_label = QLabel("")
        periodic_login_layout.addWidget(self.next_periodic_label)
        
        periodic_login_layout.addStretch()
        interval_layout.addLayout(periodic_login_layout)
        
        layout.addLayout(interval_layout)
        
        # 登录信息显示
        info_layout = QHBoxLayout()
        username = self.config['Login'].get('userName', '未设置')
        self.username_label = QLabel(f"用户: {username}")
        info_layout.addWidget(self.username_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # 文件信息
        file_info_label = QLabel(f"配置文件: {self.config_file}")
        file_info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(file_info_label)
        
        # 日志显示
        layout.addWidget(QLabel("实时日志:"))
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)
        
        self.hide()
    
    def create_system_tray(self):
        """创建系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        
        tray_menu = QMenu()
        
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        
        login_action = QAction("立即登录", self)
        login_action.triggered.connect(self.manual_login)
        tray_menu.addAction(login_action)
        
        auto_reconnect_action = QAction("自动重连", self)
        auto_reconnect_action.setCheckable(True)
        auto_reconnect_action.setChecked(self.auto_reconnect)
        auto_reconnect_action.triggered.connect(self.toggle_auto_reconnect)
        
        if self.forced_auto_reconnect:
            auto_reconnect_action.setEnabled(False)
        
        tray_menu.addAction(auto_reconnect_action)
        
        tray_menu.addSeparator()
        
        edit_config_action = QAction("编辑配置", self)
        edit_config_action.triggered.connect(self.edit_config)
        tray_menu.addAction(edit_config_action)
        
        reload_config_action = QAction("重新加载配置", self)
        reload_config_action.triggered.connect(self.reload_config)
        tray_menu.addAction(reload_config_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.update_tray_icon()
        self.tray_icon.show()
        
        self.logger.info("TRAY", "系统托盘已创建")
    
    def update_tray_icon(self):
        """更新托盘图标颜色"""
        if not hasattr(self, 'tray_icon') or self.tray_icon is None:
            return
        
        self.logger.debug("TRAY", "更新托盘图标")
        
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.auto_reconnect and self.periodic_login_interval > 0:
            color = QColor(0, 255, 0)
            tooltip_status = "自动重连+定时登录"
        elif self.auto_reconnect or self.periodic_login_interval > 0:
            color = QColor(255, 165, 0)
            tooltip_status = "部分功能开启"
        else:
            color = QColor(255, 0, 0)
            tooltip_status = "功能关闭"
        
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(8, 8, 48, 48)
        
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(24, 24, 16, 16)
        
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(f"网络登录工具 [Debug] [{tooltip_status}]")
    
    def update_status_display(self):
        """更新状态显示"""
        status_parts = []
        
        if self.forced_auto_reconnect:
            status_parts.append("<font color='darkgreen'><b>自动重连[强制开启]</b></font>")
        elif self.auto_reconnect:
            status_parts.append("<font color='green'>自动重连[开启]</font>")
        else:
            status_parts.append("<font color='red'>自动重连[关闭]</font>")
        
        if self.periodic_login_interval > 0:
            status_parts.append(f"<font color='green'>定时登录[{self.periodic_login_interval}秒]</font>")
        else:
            status_parts.append("<font color='red'>定时登录[关闭]</font>")
        
        status_parts.append("<font color='blue'>网络监控[运行中]</font>")
        
        status_text = "状态: " + " | ".join(status_parts)
        self.status_label.setText(status_text)
        self.update_tray_icon()
    
    def tray_icon_activated(self, reason):
        """托盘图标激活事件"""
        self.logger.debug("TRAY", f"托盘激活: {reason}")
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()
    
    def start_network_monitor(self):
        """启动网络监控"""
        self.logger.info("APP", "启动网络监控线程")
        self.monitor = NetworkMonitor(self.config, self.logger)
        self.monitor_thread = threading.Thread(target=self.monitor.run, daemon=True)
        self.monitor.network_status.connect(self.on_network_status_changed)
        self.monitor_thread.start()
    
    def start_periodic_login_timer(self):
        """启动定期登录定时器"""
        self.periodic_login_timer = QTimer()
        self.periodic_login_timer.timeout.connect(self.periodic_login)
        self.update_periodic_timer()
    
    def update_periodic_timer(self):
        """更新定期登录定时器"""
        if self.periodic_login_interval > 0:
            self.periodic_login_timer.start(self.periodic_login_interval * 1000)
            self.log(f"定期登录已启用，间隔: {self.periodic_login_interval}秒")
            self.update_next_periodic_time()
        else:
            self.periodic_login_timer.stop()
            self.log("定期登录已关闭")
            self.next_periodic_label.setText("")
        
        self.update_status_display()
    
    def periodic_login(self):
        """定期登录"""
        self.logger.info("LOGIN", "执行定期登录",
                        f"间隔: {self.periodic_login_interval}秒")
        self.do_login()
        self.update_next_periodic_time()
    
    def update_next_periodic_time(self):
        """更新下次定期登录时间显示"""
        if self.periodic_login_interval > 0:
            next_time = time.strftime("%H:%M:%S", 
                                     time.localtime(time.time() + self.periodic_login_interval))
            self.next_periodic_label.setText(f"下次: {next_time}")
        else:
            self.next_periodic_label.setText("")
    
    def on_network_status_changed(self, status):
        """网络状态变化"""
        self.logger.info("NETWORK", f"状态变化: {'正常' if status else '断开'}")
        
        if not status and self.auto_reconnect:
            self.logger.info("NETWORK", "检测到网络断开，触发自动重连")
            self.do_login()
    
    def manual_login(self):
        """手动登录"""
        self.logger.info("LOGIN", "用户触发手动登录")
        self.do_login()
    
    def do_login(self):
        """执行登录操作"""
        # 检查配置
        if (self.config['Login']['userName'] == 'YOUR_USERNAME' or 
            self.config['Login']['pwd'] == 'YOUR_PASSWORD' or
            'YOUR_LOGIN_SERVER' in self.config['Login']['url']):
            self.log("错误: 请先编辑配置文件，填写正确的登录信息")
            self.tray_icon.showMessage("配置错误", "请先编辑配置文件填写登录信息", 
                                      QSystemTrayIcon.MessageIcon.Warning, 5000)
            return
        
        self.logger.info("LOGIN", "开始登录流程")
        self.login_worker = LoginWorker(self.config, self.logger)
        self.login_thread = threading.Thread(target=self.login_worker.do_login, daemon=True)
        self.login_worker.login_result.connect(self.on_login_result)
        self.login_thread.start()
    
    def on_login_result(self, message, success):
        """登录结果处理"""
        self.logger.info("LOGIN", f"登录结果: {'成功' if success else '失败'}", message)
        
        if success:
            self.log(f"✓ {message}")
            self.tray_icon.showMessage("登录成功", message, 
                                      QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            self.log(f"✗ {message}")
            self.tray_icon.showMessage("登录失败", message, 
                                      QSystemTrayIcon.MessageIcon.Warning, 5000)
    
    def toggle_auto_reconnect(self, checked=None):
        """切换自动重连状态"""
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setChecked(True)
            self.log("自动重连已被配置文件锁定")
            return
        
        if isinstance(checked, bool):
            self.auto_reconnect = checked
        else:
            self.auto_reconnect = self.auto_reconnect_cb.isChecked()
        
        self.config['Settings']['auto_reconnect'] = self.auto_reconnect
        self.save_config()
        
        status = "开启" if self.auto_reconnect else "关闭"
        self.log(f"自动重连已{status}")
        self.logger.info("APP", f"自动重连状态: {status}")
        
        self.update_status_display()
    
    def update_check_interval(self, interval):
        """更新检查间隔"""
        self.check_interval = interval
        self.config['Settings']['check_interval'] = interval
        self.save_config()
        
        self.log(f"网络检查间隔已更新为 {interval} 秒")
        self.logger.info("APP", f"检查间隔更新: {interval}秒")
    
    def update_periodic_login_interval(self, interval):
        """更新定期登录间隔"""
        self.periodic_login_interval = interval
        self.config['Settings']['periodic_login_interval'] = interval
        self.save_config()
        
        if interval > 0:
            self.log(f"定期登录间隔已更新为 {interval} 秒")
        else:
            self.log("定期登录已关闭")
        
        self.update_periodic_timer()
    
    def edit_config(self):
        """编辑配置文件"""
        self.logger.info("CONFIG", "打开配置文件编辑")
        try:
            os.startfile(self.config_file)
        except Exception as e:
            self.log(f"无法打开配置文件: {e}")
            self.logger.error("CONFIG", f"打开失败: {e}")
    
    def reload_config(self):
        """重新加载配置文件"""
        self.logger.info("CONFIG", "重新加载配置")
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                new_config = yaml.safe_load(f)
            
            self.config = new_config
            
            self.auto_reconnect = self.config['Settings'].get('auto_reconnect', True)
            self.check_interval = self.config['Settings'].get('check_interval', 60)
            self.periodic_login_interval = self.config['Settings'].get('periodic_login_interval', 0)
            self.forced_auto_reconnect = self.config['Settings'].get('forced_auto_reconnect', False)
            
            if self.forced_auto_reconnect:
                self.auto_reconnect = True
                self.auto_reconnect_cb.setEnabled(False)
            else:
                self.auto_reconnect_cb.setEnabled(True)
            
            self.auto_reconnect_cb.setChecked(self.auto_reconnect)
            self.interval_spin.setValue(self.check_interval)
            
            username = self.config['Login'].get('userName', '未设置')
            self.username_label.setText(f"用户: {username}")
            
            self.update_periodic_timer()
            self.config_last_modified = os.path.getmtime(self.config_file)
            self.update_status_display()
            
            self.log("配置文件已重新加载")
            self.logger.info("CONFIG", "配置重载完成")
            
        except Exception as e:
            error_msg = f"重新加载配置文件失败: {str(e)}"
            self.log(error_msg)
            self.logger.error("CONFIG", error_msg, traceback.format_exc())
            QMessageBox.warning(self, "配置加载错误", error_msg)
    
    def toggle_hot_reload(self, state):
        """切换热更新功能"""
        if state == Qt.CheckState.Checked.value:
            self.config_monitor_timer.start(2000)
            self.log("配置文件热更新已启用")
        else:
            self.config_monitor_timer.stop()
            self.log("配置文件热更新已禁用")
    
    def check_config_update(self):
        """检查配置文件是否更新"""
        try:
            current_modified = os.path.getmtime(self.config_file)
            if current_modified != self.config_last_modified:
                self.config_last_modified = current_modified
                self.log("检测到配置文件已修改，正在重新加载...")
                self.logger.info("CONFIG", "检测到配置文件变化")
                self.reload_config()
        except Exception as e:
            pass
    
    def flush_logs(self):
        """刷新日志显示"""
        try:
            with open("debug_log.txt", 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_lines = lines[-100:]
                self.log_text.setText(''.join(recent_lines))
                self.log_text.moveCursor(self.log_text.textCursor().End)
        except:
            pass
    
    def log(self, message):
        """添加日志到UI"""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_text.append(log_entry)
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()
    
    def quit_app(self):
        """退出应用程序"""
        self.logger.info("APP", "程序退出")
        
        if hasattr(self, 'monitor'):
            self.monitor.stop()
        if hasattr(self, 'config_monitor_timer'):
            self.config_monitor_timer.stop()
        if hasattr(self, 'periodic_login_timer'):
            self.periodic_login_timer.stop()
        
        self.logger.close()
        QApplication.quit()


def main():
    """主函数"""
    print("=" * 60)
    print("AutoNetworkLogin Debug 版本")
    print("日志将保存到: debug_log.txt")
    print("=" * 60)
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    window = NetworkLoginApp()
    
    window.tray_icon.showMessage("网络登录工具 Debug版", 
                               "程序已启动，日志正在记录中...",
                               QSystemTrayIcon.MessageIcon.Information, 3000)
    
    print("程序已启动，查看 debug_log.txt 获取详细日志")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
