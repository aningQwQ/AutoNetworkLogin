import sys
import os
import threading
import time
import yaml
import socket
import psutil
from urllib.parse import urlparse
from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QMainWindow, 
                            QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QPlainTextEdit, QLabel, QCheckBox, QSpinBox, QMessageBox, QComboBox)
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtCore import QTimer, Signal, QObject, Qt

'''
- GUI框架迁移至PySide6
- 新增网卡绑定功能
- 新增跨平台网卡检测（使用psutil）
- 新增动态IP更新，每3秒刷新网卡信息
- UI下拉框自动同步网卡列表
- 新增定期登录UI开关
- 新增定期登录锁定功能
- 网卡离线时自动回退到自动模式，保留配置
- 优化UI布局，按钮靠左对齐
'''

def get_network_interfaces():
    """获取所有网卡及其IP（跨平台，使用psutil）"""
    interfaces = {}
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip and not ip.startswith('127.'):
                        interfaces[iface] = ip
    except:
        pass
    
    return interfaces


def send_http_via_socket(method, url, data=None, headers=None, bind_ip=None, timeout=10):
    """通过 socket 发送 HTTP 请求
    
    Args:
        method: HTTP 方法
        url: 完整 URL
        data: POST 数据
        headers: 请求头字典
        bind_ip: 绑定的源 IP
        timeout: 超时时间
    
    Returns:
        response: (status_code, response_body, response_headers)
    """
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path or '/'
    if parsed.query:
        path = path + '?' + parsed.query
    
    if headers is None:
        headers = {}
    if 'Host' not in headers:
        headers['Host'] = host
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    
    try:
        if bind_ip:
            sock.bind((bind_ip, 0))
        
        sock.connect((host, port))
        
        request_lines = [f"{method} {path} HTTP/1.1"]
        for key, value in headers.items():
            request_lines.append(f"{key}: {value}")
        
        if data:
            if isinstance(data, dict):
                body = '&'.join(f"{k}={v}" for k, v in data.items())
            else:
                body = data
            request_lines.append(f"Content-Length: {len(body)}")
        
        request_lines.append('Connection: close')
        request_lines.append('')
        
        request = '\r\n'.join(request_lines)
        if data:
            if isinstance(data, dict):
                body = '&'.join(f"{k}={v}" for k, v in data.items())
            else:
                body = data
            request += '\r\n' + body
        
        sock.sendall(request.encode('utf-8'))
        
        response_data = b''
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
            except socket.timeout:
                break
        
        sock.close()
        
        response_str = response_data.decode('utf-8', errors='ignore')
        parts = response_str.split('\r\n\r\n', 1)
        
        if len(parts) < 2:
            return (0, response_str, {})
        
        header_part = parts[0]
        body_part = parts[1]
        
        status_line = header_part.split('\r\n')[0]
        try:
            status_code = int(status_line.split()[1])
        except:
            status_code = 0
        
        response_headers = {}
        for line in header_part.split('\r\n')[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                response_headers[key.strip()] = value.strip()
        
        return (status_code, body_part, response_headers)
        
    except Exception as e:
        sock.close()
        raise e


def check_network_connectivity(test_url, bind_ip=None, timeout=5):
    """检测网络连通性（通过 socket）
    
    Returns:
        True if connected, False otherwise
    """
    try:
        parsed = urlparse(test_url)
        host = parsed.hostname or 'www.baidu.com'
        port = parsed.port or 80
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        if bind_ip:
            sock.bind((bind_ip, 0))
        
        sock.connect((host, port))
        sock.close()
        return True
    except:
        return False

class LoginWorker(QObject):
    """登录工作线程"""
    login_result = Signal(str, bool)  # message, success
    
    def __init__(self, config, bind_ip=None):
        super().__init__()
        self.config = config
        self.bind_ip = bind_ip
    
    def do_login(self):
        """执行登录操作"""
        try:
            login_url = self.config['Login']['url']
            login_data = self.get_login_data()
            headers = self.get_headers()
            
            status_code, response_text, response_headers = send_http_via_socket(
                'POST', login_url, data=login_data, headers=headers, 
                bind_ip=self.bind_ip, timeout=10
            )
            
            if 'success' in response_text.lower() or 'logon success' in response_text.lower():
                self.login_result.emit("登录成功", True)
            else:
                self.login_result.emit(f"登录响应: {response_text[:100]}", False)
                
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
    network_status = Signal(bool)  # True=网络正常, False=网络异常
    
    def __init__(self, config, bind_ip=None):
        super().__init__()
        self.config = config
        self.running = True
        self.bind_ip = bind_ip
    
    def stop(self):
        """停止监控"""
        self.running = False
    
    def run(self):
        """运行网络监控"""
        while self.running:
            try:
                test_url = self.config['Settings'].get('test_url', 'http://www.baidu.com')
                test_timeout = self.config['Settings'].get('test_timeout', 5)
                
                status = check_network_connectivity(test_url, self.bind_ip, test_timeout)
                
                self.network_status.emit(status)
            except:
                self.network_status.emit(False)
            
            time.sleep(self.config['Settings'].get('check_interval', 60))

class NetworkLoginApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config_file = "network_config.yaml"
        self.template_file = "network_config_template.yaml"
        self.config = {}
        
        # 加载或创建配置
        self.load_or_create_config()
        
        # 初始化设置
        self.auto_reconnect = self.config['Settings'].get('auto_reconnect', True)
        self.check_interval = self.config['Settings'].get('check_interval', 60)
        self.periodic_login_interval = self.config['Settings'].get('periodic_login_interval', 0)  # 0表示关闭
        self.forced_auto_reconnect = self.config['Settings'].get('forced_auto_reconnect', False)  # 配置锁定自动登录
        self.forced_periodic_login = self.config['Settings'].get('forced_periodic_login', False)  # 配置锁定定期登录
        self.network_interface = self.config['Settings'].get('network_interface', 'auto')
        
        # 获取绑定 IP
        self.bind_ip = self.get_bind_ip()
        
        # 获取所有网卡列表
        self.available_interfaces = get_network_interfaces()
        
        # 如果强制开启自动重连，则覆盖当前设置
        if self.forced_auto_reconnect:
            self.auto_reconnect = True
        
        # 如果强制开启定期登录，则设置间隔
        if self.forced_periodic_login:
            if self.periodic_login_interval == 0:
                self.periodic_login_interval = 600  # 默认600秒
        
        # 初始化UI
        self.init_ui()
        
        # 创建系统托盘（必须先创建）
        self.create_system_tray()
        
        # 启动网络监控
        self.start_network_monitor()
        
        # 启动定期登录定时器
        self.start_periodic_login_timer()
        
        # 更新状态显示（必须在创建托盘后调用）
        self.update_status_display()
        
        # 配置文件监控
        self.config_last_modified = os.path.getmtime(self.config_file)
        self.config_monitor_timer = QTimer()
        self.config_monitor_timer.timeout.connect(self.check_config_update)
        self.config_monitor_timer.start(2000)  # 每2秒检查一次
        
        # 网卡IP动态更新
        self.interface_update_timer = QTimer()
        self.interface_update_timer.timeout.connect(self.update_interface_info)
        self.interface_update_timer.start(3000)  # 每3秒更新一次网卡信息
    
    def update_interface_info(self):
        """定时更新网卡信息和IP"""
        old_bind_ip = self.bind_ip
        
        # 更新网卡列表
        self.available_interfaces = get_network_interfaces()
        
        # 更新绑定IP（如果配置的网卡不存在，会回退到auto，返回None）
        self.bind_ip = self.get_bind_ip()
        
        # 保存配置值用于恢复选择
        configured_interface = self.network_interface
        
        # 更新UI下拉框
        current_selection = self.interface_combo.currentData()
        self.interface_combo.blockSignals(True)
        self.interface_combo.clear()
        self.interface_combo.addItem("自动", "auto")
        for iface_name, iface_ip in self.available_interfaces.items():
            display_text = f"{iface_name} ({iface_ip})"
            self.interface_combo.addItem(display_text, iface_name)
        
        # 优先尝试恢复配置的网卡选择
        restored = False
        for i in range(self.interface_combo.count()):
            if self.interface_combo.itemData(i) == configured_interface:
                self.interface_combo.setCurrentIndex(i)
                restored = True
                break
        
        # 如果配置的网卡不存在，尝试恢复之前的选择
        if not restored:
            for i in range(self.interface_combo.count()):
                if self.interface_combo.itemData(i) == current_selection:
                    self.interface_combo.setCurrentIndex(i)
                    break
        
        self.interface_combo.blockSignals(False)
        
        # 如果绑定IP变化了，更新状态显示
        if old_bind_ip != self.bind_ip:
            self.update_status_display()
    
    def get_bind_ip(self):
        """根据配置获取绑定的 IP 地址"""
        interface_setting = self.config['Settings'].get('network_interface', 'auto')
        
        if interface_setting == 'auto' or not interface_setting:
            return None
        
        interfaces = get_network_interfaces()
        
        if interface_setting in interfaces:
            return interfaces[interface_setting]
        
        if interface_setting in interfaces.values():
            return interface_setting
        
        return None
    
    def create_template_config(self):
        """创建带注释的配置模板文件"""
        template_content = '''# 网络登录工具配置文件模板
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
  
  # 强制开启定期登录（只能通过配置文件修改）
  # 如果设置为true，程序将强制开启定期登录，UI中的选项将被禁用
  forced_periodic_login: false
  
  # 网卡绑定设置
  # 设置为 "auto" 自动选择网卡，或指定网卡名如 "eth0"、"en0"
  # 也可以直接指定 IP 地址，如 "192.168.1.100"
  # Linux 可通过 "ip addr" 查看网卡，Windows 用 "ipconfig"，macOS 用 "ifconfig"
  network_interface: "auto"
'''
        
        with open(self.template_file, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        print(f"已创建配置模板文件: {self.template_file}")
    
    def create_default_config(self):
        """从模板文件创建默认的用户配置文件（不含注释）"""
        try:
            # 读取模板文件
            with open(self.template_file, 'r', encoding='utf-8') as f:
                template_config = yaml.safe_load(f)
            
            # 直接保存模板配置为用户配置（YAML库会自动去掉注释）
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(template_config, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            print(f"已从模板创建默认配置文件: {self.config_file}")
            
        except Exception as e:
            print(f"从模板创建配置文件失败: {e}")
            # 如果读取模板失败，创建最小配置
            fallback_config = {
                'Login': {
                    'url': 'http://YOUR_LOGIN_SERVER_URL/ac_portal/login.php',
                    'opr': 'pwdLogin',
                    'userName': 'YOUR_USERNAME',
                    'pwd': 'YOUR_PASSWORD',
                    'auth_tag': 'TIMESTAMP',
                    'rememberPwd': '0'
                },
                'Headers': {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                'Settings': {
                    'auto_reconnect': True,
                    'check_interval': 60,
                    'test_url': 'http://www.baidu.com',
                    'test_timeout': 5,
                    'periodic_login_interval': 0,
                    'forced_auto_reconnect': False,
                    'forced_periodic_login': False,
                    'network_interface': 'auto'
                }
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(fallback_config, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            print(f"已创建最小化配置文件: {self.config_file}")
    
    def load_or_create_config(self):
        """加载或创建配置文件"""
        # 如果配置文件不存在，创建配置模板和默认配置
        if not os.path.exists(self.config_file):
            # 先创建模板文件（带注释）
            self.create_template_config()
            # 再从模板创建默认配置文件（不含注释）
            self.create_default_config()
        
        # 如果模板文件不存在，也创建它（用于后续参考）
        if not os.path.exists(self.template_file):
            self.create_template_config()
        
        # 加载用户配置文件
        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
    
    def save_config(self):
        """保存配置到文件"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, indent=2)
    
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("AutoNetworkLogin")
        self.setGeometry(100, 100, 500, 450)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 状态显示
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 正在初始化...")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # 控制按钮（靠左对齐）
        button_layout = QHBoxLayout()
        button_layout.setAlignment(Qt.AlignLeft)
        
        self.login_btn = QPushButton("立即登录")
        self.login_btn.clicked.connect(self.manual_login)
        button_layout.addWidget(self.login_btn)
        
        self.auto_reconnect_cb = QCheckBox("自动重连")
        self.auto_reconnect_cb.setChecked(self.auto_reconnect)
        self.auto_reconnect_cb.stateChanged.connect(self.toggle_auto_reconnect)
        
        # 如果强制开启自动重连，则禁用复选框
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setEnabled(False)
            self.auto_reconnect_cb.setToolTip("已通过配置文件锁定")
        
        button_layout.addWidget(self.auto_reconnect_cb)
        
        # 定期登录开关
        self.periodic_login_cb = QCheckBox("定期登录")
        self.periodic_login_cb.setChecked(self.periodic_login_interval > 0)
        self.periodic_login_cb.stateChanged.connect(self.toggle_periodic_login)
        
        # 如果强制开启定期登录，则禁用复选框
        if self.forced_periodic_login:
            self.periodic_login_cb.setEnabled(False)
            self.periodic_login_cb.setToolTip("已通过配置文件锁定")
        
        button_layout.addWidget(self.periodic_login_cb)
        
        layout.addLayout(button_layout)
        
        # 配置管理按钮
        config_button_layout = QHBoxLayout()
        
        self.edit_config_btn = QPushButton("编辑配置")
        self.edit_config_btn.clicked.connect(self.edit_config)
        config_button_layout.addWidget(self.edit_config_btn)
        
        self.edit_template_btn = QPushButton("查看模板")
        self.edit_template_btn.clicked.connect(self.edit_template)
        config_button_layout.addWidget(self.edit_template_btn)
        
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
        periodic_login_layout.addWidget(self.next_periodic_label)
        
        periodic_login_layout.addStretch()
        interval_layout.addLayout(periodic_login_layout)
        
        layout.addLayout(interval_layout)
        
        # 网卡选择
        network_interface_layout = QHBoxLayout()
        network_interface_layout.addWidget(QLabel("网卡绑定:"))
        
        self.interface_combo = QComboBox()
        self.interface_combo.addItem("自动", "auto")
        for iface_name, iface_ip in self.available_interfaces.items():
            display_text = f"{iface_name} ({iface_ip})"
            self.interface_combo.addItem(display_text, iface_name)
        
        current_setting = self.config['Settings'].get('network_interface', 'auto')
        if current_setting == 'auto':
            self.interface_combo.setCurrentIndex(0)
        else:
            for i in range(self.interface_combo.count()):
                if self.interface_combo.itemData(i) == current_setting:
                    self.interface_combo.setCurrentIndex(i)
                    break
        
        self.interface_combo.currentIndexChanged.connect(self.update_network_interface)
        network_interface_layout.addWidget(self.interface_combo)
        
        network_interface_layout.addStretch()
        layout.addLayout(network_interface_layout)
        
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
        
        # 文件信息
        file_info_label = QLabel(f"配置文件: {self.config_file} | 模板文件: {self.template_file}")
        file_info_label.setStyleSheet("color: gray;")
        layout.addWidget(file_info_label)
        
        # 日志显示
        layout.addWidget(QLabel("运行日志:"))
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        layout.addWidget(self.log_text)
        
        # 隐藏窗口
        self.hide()
    
    def create_system_tray(self):
        """创建系统托盘"""
        # 创建托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        
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
        
        view_template_action = QAction("查看模板", self)
        view_template_action.triggered.connect(self.edit_template)
        tray_menu.addAction(view_template_action)
        
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
        
        # 立即设置托盘图标
        self.update_tray_icon()
        
        # 显示托盘图标
        self.tray_icon.show()
    
    def update_tray_icon(self):
        """更新托盘图标颜色"""
        if not hasattr(self, 'tray_icon') or self.tray_icon is None:
            return
            
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 根据状态选择颜色
        if self.auto_reconnect and self.periodic_login_interval > 0:
            # 绿色：两个功能都开启
            color = QColor(0, 255, 0)  # 绿色
            tooltip_status = "自动重连+定时登录"
        elif self.auto_reconnect or self.periodic_login_interval > 0:
            # 橙色：只开启一个功能
            color = QColor(255, 165, 0)  # 橙色
            tooltip_status = "部分功能开启"
        else:
            # 红色：两个功能都关闭
            color = QColor(255, 0, 0)  # 红色
            tooltip_status = "功能关闭"
        
        # 绘制圆形图标
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(8, 8, 48, 48)
        
        # 添加内部小圆点表示活动状态
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(24, 24, 16, 16)
        
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        
        interface_info = self.bind_ip if self.bind_ip else "自动"
        self.tray_icon.setToolTip(f"网络登录工具 [{tooltip_status}] [{interface_info}]")
    
    def update_status_display(self):
        """更新状态显示"""
        status_parts = []
        
        # 自动重连状态
        if self.forced_auto_reconnect:
            status_parts.append("<font color='darkgreen'><b>自动重连</b></font>")
        elif self.auto_reconnect:
            status_parts.append("<font color='green'>自动重连[开启]</font>")
        else:
            status_parts.append("<font color='red'>自动重连[关闭]</font>")
        
        # 定期登录状态
        if self.periodic_login_interval > 0:
            status_parts.append(f"<font color='green'>定时登录[{self.periodic_login_interval}秒]</font>")
        else:
            status_parts.append("<font color='red'>定时登录[关闭]</font>")
        
        # 网络监控状态
        status_parts.append("<font color='blue'>网络监控[运行中]</font>")
        
        # 网卡绑定状态
        if self.bind_ip:
            status_parts.append(f"<font color='purple'>网卡[{self.bind_ip}]</font>")
        else:
            status_parts.append("<font color='gray'>网卡[自动]</font>")
        
        status_text = "状态: " + " | ".join(status_parts)
        self.status_label.setText(status_text)
        
        # 更新托盘图标颜色
        self.update_tray_icon()
    
    def tray_icon_activated(self, reason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
    
    def start_network_monitor(self):
        """启动网络监控"""
        self.monitor = NetworkMonitor(self.config, self.bind_ip)
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
        
        # 更新状态显示
        self.update_status_display()
    
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
                                     QSystemTrayIcon.Warning, 5000)
            return
            
        # 在工作线程中执行登录
        self.login_worker = LoginWorker(self.config, self.bind_ip)
        self.login_thread = threading.Thread(target=self.login_worker.do_login, daemon=True)
        self.login_worker.login_result.connect(self.on_login_result)
        self.login_thread.start()
    
    def on_login_result(self, message, success):
        """登录结果处理"""
        if success:
            self.log(f"✓ {message}")
            self.tray_icon.showMessage("登录成功", message, QSystemTrayIcon.Information, 3000)
        else:
            self.log(f"✗ {message}")
            self.tray_icon.showMessage("登录失败", message, QSystemTrayIcon.Warning, 5000)
    
    def toggle_auto_reconnect(self, checked=None):
        """切换自动重连状态"""
        # 如果强制开启自动重连，则不允许修改
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setChecked(True)  # 强制保持选中状态
            self.log("自动重连已锁定，无法修改")
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
        
        # 更新状态显示
        self.update_status_display()
    
    def toggle_periodic_login(self, checked=None):
        """切换定期登录状态"""
        # 如果强制开启定期登录，则不允许修改
        if self.forced_periodic_login:
            self.periodic_login_cb.setChecked(True)  # 强制保持选中状态
            self.log("定期登录已锁定，无法修改")
            return
        
        if isinstance(checked, bool):
            is_enabled = checked
        else:
            is_enabled = self.periodic_login_cb.isChecked()
        
        # 更新定期登录间隔
        if is_enabled and self.periodic_login_interval == 0:
            self.periodic_login_interval = 600  # 默认600秒
            self.periodic_interval_spin.setValue(600)
        
        # 更新配置
        self.config['Settings']['periodic_login_interval'] = self.periodic_login_interval
        self.save_config()
        
        # 重启定时器
        self.start_periodic_login_timer()
        
        status = "开启" if self.periodic_login_interval > 0 else "关闭"
        self.log(f"定期登录已{status}")
        
        # 更新状态显示
        self.update_status_display()
    
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
    
    def update_network_interface(self, index):
        """更新网卡绑定设置"""
        interface_name = self.interface_combo.itemData(index)
        self.network_interface = interface_name
        self.config['Settings']['network_interface'] = interface_name
        self.save_config()
        
        self.bind_ip = self.get_bind_ip()
        
        if interface_name == 'auto':
            self.log("网卡绑定已设置为自动")
        else:
            self.log(f"网卡绑定已设置为: {interface_name}")
        
        self.update_status_display()
    
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
    
    def edit_template(self):
        """查看配置模板"""
        try:
            os.startfile(self.template_file)  # Windows
        except:
            try:
                os.system(f"xdg-open {self.template_file}")  # Linux
            except:
                try:
                    os.system(f"open {self.template_file}")  # macOS
                except:
                    self.log(f"无法打开模板文件: {self.template_file}")
                    QMessageBox.information(self, "网络登录工具", 
                                          f"无法打开模板文件: {self.template_file}")
    
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
            self.forced_periodic_login = self.config['Settings'].get('forced_periodic_login', False)
            self.network_interface = self.config['Settings'].get('network_interface', 'auto')
            
            # 重新获取绑定 IP 和网卡列表
            self.bind_ip = self.get_bind_ip()
            self.available_interfaces = get_network_interfaces()
            
            # 如果强制开启自动重连，则覆盖当前设置
            if self.forced_auto_reconnect:
                self.auto_reconnect = True
                self.auto_reconnect_cb.setEnabled(False)
                self.auto_reconnect_cb.setToolTip("已通过配置文件锁定")
            else:
                self.auto_reconnect_cb.setEnabled(True)
                self.auto_reconnect_cb.setToolTip("")
            
            # 如果强制开启定期登录，则覆盖当前设置
            if self.forced_periodic_login:
                if self.periodic_login_interval == 0:
                    self.periodic_login_interval = 600
                self.periodic_login_cb.setEnabled(False)
                self.periodic_login_cb.setToolTip("已通过配置文件锁定")
            else:
                self.periodic_login_cb.setEnabled(True)
                self.periodic_login_cb.setToolTip("")
            
            self.auto_reconnect_cb.setChecked(self.auto_reconnect)
            self.periodic_login_cb.setChecked(self.periodic_login_interval > 0)
            self.interval_spin.setValue(self.check_interval)
            self.periodic_interval_spin.setValue(self.periodic_login_interval)
            
            # 更新用户名显示
            username = self.config['Login'].get('userName', '未设置')
            self.username_label.setText(f"用户: {username}")
            
            # 更新网卡下拉框
            current_setting = self.config['Settings'].get('network_interface', 'auto')
            for i in range(self.interface_combo.count()):
                if self.interface_combo.itemData(i) == current_setting:
                    self.interface_combo.setCurrentIndex(i)
                    break
            
            # 更新定期登录定时器
            self.update_periodic_timer()
            
            # 更新最后修改时间
            self.config_last_modified = os.path.getmtime(self.config_file)
            
            # 更新状态显示
            self.update_status_display()
            
            self.log("配置文件已重新加载")
            self.tray_icon.showMessage("配置更新", "配置文件已重新加载", 
                                     QSystemTrayIcon.Information, 3000)
            
        except Exception as e:
            error_msg = f"重新加载配置文件失败: {str(e)}"
            self.log(error_msg)
            QMessageBox.warning(self, "配置加载错误", error_msg)
    
    def toggle_hot_reload(self, state):
        """切换热更新功能"""
        if state == Qt.Checked:
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
        self.log_text.appendPlainText(log_entry)
    
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
        if hasattr(self, 'interface_update_timer'):
            self.interface_update_timer.stop()
        QApplication.quit()

def main():
    # 创建应用
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 创建主窗口
    window = NetworkLoginApp()
    
    # 显示通知
    window.tray_icon.showMessage("网络登录工具", "程序已启动并在系统托盘中运行", 
                               QSystemTrayIcon.Information, 3000)
    window.log("网络登录工具已启动")
    window.log("首次使用请先编辑配置文件，填写正确的登录信息")
    window.log(f"配置文件: {window.config_file}")
    window.log(f"模板文件: {window.template_file}")
    
    # 运行应用
    sys.exit(app.exec())

if __name__ == "__main__":
    main()