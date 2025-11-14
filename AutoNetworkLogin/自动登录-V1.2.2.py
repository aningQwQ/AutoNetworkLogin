import sys
import os
import requests
import threading
import time
import yaml
from PyQt6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QMainWindow, 
                            QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QTextEdit, QLabel, QCheckBox, QSpinBox, QMessageBox)
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, Qt

class LoginWorker(QObject):
    """登录工作线程"""
    login_result = pyqtSignal(str, bool)  # message, success
    
    def __init__(self, config):
        super().__init__()
        self.config = config
    
    def do_login(self):
        """执行登录操作"""
        try:
            login_url = self.config['Login']['url']
            login_data = self.get_login_data()
            headers = self.get_headers()
            
            response = requests.post(
                login_url,
                data=login_data,
                headers=headers,
                timeout=10
            )
            
            # 尝试解析响应为JSON，如果不是JSON则使用文本
            try:
                result = response.json()
                if result.get('success'):
                    self.login_result.emit(f"登录成功: {result.get('msg', '')}", True)
                else:
                    self.login_result.emit(f"登录失败: {result.get('msg', '未知错误')}", False)
            except ValueError:
                # 如果不是JSON，使用文本响应
                if 'success' in response.text.lower() or 'logon success' in response.text.lower():
                    self.login_result.emit("登录成功", True)
                else:
                    self.login_result.emit(f"登录响应: {response.text[:100]}", False)
                
        except requests.exceptions.RequestException as e:
            self.login_result.emit(f"连接失败: {str(e)}", False)
        except Exception as e:
            self.login_result.emit(f"错误: {str(e)}", False)
    
    def get_login_data(self):
        """从配置获取登录数据"""
        return {
            "opr": self.config['Login']['opr'],
            "userName": self.config['Login']['userName'],
            "pwd": self.config['Login']['pwd'],
            "auth_tag": self.config['Login']['auth_tag'],
            "rememberPwd": self.config['Login']['rememberPwd']
        }
    
    def get_headers(self):
        """从配置获取请求头"""
        return self.config['Headers']

class NetworkMonitor(QObject):
    """网络监控器"""
    network_status = pyqtSignal(bool)  # True=网络正常, False=网络异常
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
    
    def stop(self):
        """停止监控"""
        self.running = False
    
    def run(self):
        """运行网络监控"""
        while self.running:
            try:
                test_url = self.config['Settings'].get('test_url', 'http://www.baidu.com')
                test_timeout = self.config['Settings'].get('test_timeout', 5)
                
                response = requests.get(test_url, timeout=test_timeout)
                self.network_status.emit(response.status_code == 200)
            except:
                self.network_status.emit(False)
            
            time.sleep(self.config['Settings'].get('check_interval', 60))

class NetworkLoginApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config_file = "network_config.yaml"
        self.config = {}
        
        # 加载或创建默认配置
        self.load_or_create_config()
        
        # 初始化设置
        self.auto_reconnect = self.config['Settings'].get('auto_reconnect', True)
        self.check_interval = self.config['Settings'].get('check_interval', 60)
        self.periodic_login_interval = self.config['Settings'].get('periodic_login_interval', 0)  # 0表示关闭
        self.forced_auto_reconnect = self.config['Settings'].get('forced_auto_reconnect', False)  # 配置锁定自动登录
        
        # 如果强制开启自动重连，则覆盖当前设置
        if self.forced_auto_reconnect:
            self.auto_reconnect = True
        
        # 初始化UI
        self.init_ui()
        
        # 启动网络监控
        self.start_network_monitor()
        
        # 启动定期登录定时器
        self.start_periodic_login_timer()
        
        # 创建系统托盘
        self.create_system_tray()
        
        # 配置文件监控
        self.config_last_modified = os.path.getmtime(self.config_file)
        self.config_monitor_timer = QTimer()
        self.config_monitor_timer.timeout.connect(self.check_config_update)
        self.config_monitor_timer.start(2000)  # 每2秒检查一次
    
    def load_or_create_config(self):
        """加载或创建配置文件"""
        if not os.path.exists(self.config_file):
            self.create_default_config()
        
        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
    
    def create_default_config(self):
        """创建带注释的默认配置文件"""
        config_content = '''# 网络登录工具配置文件
# 请按照以下步骤获取配置信息：
# 1. 打开浏览器，访问任意网页触发跳转到登录页面
# 2. 按F12打开开发者工具，切换到 "网络(Network)" 标签
# 3. 在登录页面输入账号密码并登录
# 4. 在网络请求列表中找到 "login.php" 请求
# 5. 右键该请求，选择 "Copy" -> "Copy as cURL"
# 6. 将复制的 cURL命令 及 以下内容 提供给AI助手来生成正确的配置

# 登录配置部分
Login:
  # 登录接口URL
  url: "http://YOUR_LOGIN_SERVER_URL/ac_portal/login.php"
  # 登录操作类型
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
  Cookie: "YOUR_ACTUAL_COOKIE"  # 从cURL的Cookie头提取
  DNT: "1"
  Host: "YOUR_LOGIN_SERVER_HOST"  # 从URL中提取主机名
  Origin: "http://YOUR_LOGIN_SERVER_HOST"  # 与Host相同
  Pragma: "no-cache"
  Referer: "YOUR_LOGIN_PAGE_URL"  # 从cURL的Referer头提取
  User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"  # 从cURL提取
  X-Requested-With: "XMLHttpRequest"

# 程序运行设置
Settings:
  # 自动重连功能
  auto_reconnect: true
  
  # 网络连通性检查间隔（秒）
  check_interval: 60
  
  # 用于测试网络连通性的网址
  test_url: "http://www.baidu.com"
  
  # 网络测试超时时间（秒）
  test_timeout: 5
  
  # 定期强制登录间隔（秒），0表示关闭此功能
  # 建议设置为3600(1小时)或7200(2小时)，用于解决特殊网络环境问题
  periodic_login_interval: 0
  
  # 强制开启自动重连（只能通过配置文件修改）
  # 如果设置为true，程序将强制开启自动重连，UI中的选项将被禁用
  forced_auto_reconnect: false
'''
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        # 重新加载配置
        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        print(f"已创建带注释的配置文件: {self.config_file}")
    
    def save_config(self):
        """保存配置到文件"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, indent=2)
    
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("网络登录工具")
        self.setGeometry(100, 100, 500, 450)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 状态显示 - 将强制自动重连提示放在这里
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 运行中")
        status_layout.addWidget(self.status_label)
        
        # 强制自动重连状态显示
        self.forced_auto_label = QLabel("")
        self.forced_auto_label.setStyleSheet("color: red; font-weight: bold;")
        status_layout.addWidget(self.forced_auto_label)
        
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
        
        # 如果强制开启自动重连，则禁用复选框
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setEnabled(False)
            self.auto_reconnect_cb.setToolTip("强制自动重连已开启，只能通过配置文件修改")
            self.forced_auto_label.setText("强制自动重连")
        
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
        
        # 网络检查间隔
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
        self.periodic_interval_spin.setRange(0, 86400)  # 0到24小时
        self.periodic_interval_spin.setValue(self.periodic_login_interval)
        self.periodic_interval_spin.setSpecialValueText("关闭")
        self.periodic_interval_spin.valueChanged.connect(self.update_periodic_login_interval)
        periodic_login_layout.addWidget(self.periodic_interval_spin)
        
        # 显示下次定期登录时间
        self.next_periodic_label = QLabel("")
        self.update_next_periodic_time()
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
        
        # 配置说明
        help_label = QLabel("首次使用请先编辑配置文件，填写正确的登录信息")
        help_label.setStyleSheet("color: blue; font-weight: bold;")
        layout.addWidget(help_label)
        
        # 日志显示
        layout.addWidget(QLabel("运行日志:"))
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        
        # 隐藏窗口
        self.hide()
    
    def create_system_tray(self):
        """创建系统托盘"""
        # 创建托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        
        # 创建简单的图标
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 128, 0))  # 绿色背景
        painter = QPainter(pixmap)
        painter.fillRect(16, 16, 32, 32, QColor(255, 255, 255))  # 白色方块
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("网络登录工具")
        
        # 创建托盘菜单
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
        
        # 如果强制开启自动重连，则禁用托盘菜单中的选项
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
        
        # 托盘图标点击事件
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # 显示托盘图标
        self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()
    
    def start_network_monitor(self):
        """启动网络监控"""
        self.monitor = NetworkMonitor(self.config)
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
            self.periodic_login_timer.start(self.periodic_login_interval * 1000)  # 转换为毫秒
            self.log(f"定期登录已启用，间隔: {self.periodic_login_interval}秒")
            self.update_next_periodic_time()
        else:
            self.periodic_login_timer.stop()
            self.log("定期登录已关闭")
            self.next_periodic_label.setText("")
    
    def periodic_login(self):
        """定期登录"""
        self.log(f"执行定期登录（间隔: {self.periodic_login_interval}秒）...")
        self.do_login()
        self.update_next_periodic_time()
    
    def update_next_periodic_time(self):
        """更新下次定期登录时间显示"""
        if self.periodic_login_interval > 0:
            next_time = time.strftime("%H:%M:%S", time.localtime(time.time() + self.periodic_login_interval))
            self.next_periodic_label.setText(f"下次: {next_time}")
        else:
            self.next_periodic_label.setText("")
    
    def on_network_status_changed(self, status):
        """网络状态变化"""
        if not status and self.auto_reconnect:
            self.log("检测到网络不可用，尝试登录...")
            self.do_login()
    
    def manual_login(self):
        """手动登录"""
        self.log("执行手动登录...")
        self.do_login()
    
    def do_login(self):
        """执行登录操作"""
        # 检查配置是否已填写
        if (self.config['Login']['userName'] == 'YOUR_USERNAME' or 
            self.config['Login']['pwd'] == 'YOUR_PASSWORD' or
            'YOUR_LOGIN_SERVER' in self.config['Login']['url']):
            self.log("错误: 请先编辑配置文件，填写正确的登录信息")
            self.tray_icon.showMessage("配置错误", "请先编辑配置文件填写登录信息", 
                                     QSystemTrayIcon.MessageIcon.Warning, 5000)
            return
            
        # 在工作线程中执行登录
        self.login_worker = LoginWorker(self.config)
        self.login_thread = threading.Thread(target=self.login_worker.do_login, daemon=True)
        self.login_worker.login_result.connect(self.on_login_result)
        self.login_thread.start()
    
    def on_login_result(self, message, success):
        """登录结果处理"""
        if success:
            self.log(f"✓ {message}")
            self.tray_icon.showMessage("登录成功", message, QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            self.log(f"✗ {message}")
            self.tray_icon.showMessage("登录失败", message, QSystemTrayIcon.MessageIcon.Warning, 5000)
    
    def toggle_auto_reconnect(self, checked=None):
        """切换自动重连状态"""
        # 如果强制开启自动重连，则不允许修改
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setChecked(True)  # 强制保持选中状态
            self.log("自动重连已被配置文件锁定，无法修改")
            return
        
        if isinstance(checked, bool):
            self.auto_reconnect = checked
        else:
            # 来自复选框的信号
            self.auto_reconnect = self.auto_reconnect_cb.isChecked()
        
        # 更新配置
        self.config['Settings']['auto_reconnect'] = self.auto_reconnect
        self.save_config()
        
        status = "开启" if self.auto_reconnect else "关闭"
        self.log(f"自动重连已{status}")
    
    def update_check_interval(self, interval):
        """更新检查间隔"""
        self.check_interval = interval
        self.config['Settings']['check_interval'] = interval
        self.save_config()
        
        self.log(f"网络检查间隔已更新为 {interval} 秒")
    
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
        try:
            os.startfile(self.config_file)  # Windows
        except:
            try:
                os.system(f"xdg-open {self.config_file}")  # Linux
            except:
                try:
                    os.system(f"open {self.config_file}")  # macOS
                except:
                    self.log(f"无法打开配置文件，请手动编辑: {self.config_file}")
                    QMessageBox.information(self, "网络登录工具", 
                                          f"无法打开配置文件，请手动编辑: {self.config_file}")
    
    def reload_config(self):
        """重新加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                new_config = yaml.safe_load(f)
            
            # 更新配置
            self.config = new_config
            
            # 更新UI状态
            self.auto_reconnect = self.config['Settings'].get('auto_reconnect', True)
            self.check_interval = self.config['Settings'].get('check_interval', 60)
            self.periodic_login_interval = self.config['Settings'].get('periodic_login_interval', 0)
            self.forced_auto_reconnect = self.config['Settings'].get('forced_auto_reconnect', False)
            
            # 如果强制开启自动重连，则覆盖当前设置
            if self.forced_auto_reconnect:
                self.auto_reconnect = True
                self.auto_reconnect_cb.setEnabled(False)
                self.auto_reconnect_cb.setToolTip("强制自动重连已开启，只能通过配置文件修改")
                self.forced_auto_label.setText("强制自动重连")
            else:
                self.auto_reconnect_cb.setEnabled(True)
                self.auto_reconnect_cb.setToolTip("")
                self.forced_auto_label.setText("")
            
            self.auto_reconnect_cb.setChecked(self.auto_reconnect)
            self.interval_spin.setValue(self.check_interval)
            self.periodic_interval_spin.setValue(self.periodic_login_interval)
            
            # 更新用户名显示
            username = self.config['Login'].get('userName', '未设置')
            self.username_label.setText(f"用户: {username}")
            
            # 更新定期登录定时器
            self.update_periodic_timer()
            
            # 更新最后修改时间
            self.config_last_modified = os.path.getmtime(self.config_file)
            
            self.log("配置文件已重新加载")
            self.tray_icon.showMessage("配置更新", "配置文件已重新加载", 
                                     QSystemTrayIcon.MessageIcon.Information, 3000)
            
        except Exception as e:
            error_msg = f"重新加载配置文件失败: {str(e)}"
            self.log(error_msg)
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
                self.reload_config()
        except Exception as e:
            # 文件可能正在被编辑，忽略错误
            pass
    
    def log(self, message):
        """添加日志"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
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
        if hasattr(self, 'monitor'):
            self.monitor.stop()
        if hasattr(self, 'config_monitor_timer'):
            self.config_monitor_timer.stop()
        if hasattr(self, 'periodic_login_timer'):
            self.periodic_login_timer.stop()
        QApplication.quit()

def main():
    # 创建应用
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 创建主窗口
    window = NetworkLoginApp()
    
    # 显示通知
    window.tray_icon.showMessage("网络登录工具", "程序已启动并在系统托盘中运行", 
                               QSystemTrayIcon.MessageIcon.Information, 3000)
    window.log("网络登录工具已启动")
    window.log("首次使用请先编辑配置文件，填写正确的登录信息")
    
    # 运行应用
    sys.exit(app.exec())

if __name__ == "__main__":
    main()