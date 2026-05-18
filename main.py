"""主程序 - 网络登录工具插件化框架

架构：
- 主程序：托盘、定时器、热更新、开机启动、UI 导航
- 插件：全权负责协议登录/登出/在线检测及配置界面
"""
import sys
import os
import threading
import time
from typing import Optional

from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QMainWindow,
                               QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QPlainTextEdit, QLabel, QCheckBox, QSpinBox,
                               QMessageBox, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QStackedWidget, QComboBox)
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtCore import QTimer, Signal, QObject, Qt

from config_manager import ConfigManager
from plugin_loader import PluginLoader
from plugin_base import ProtocolPlugin, ProtocolHandler


class NetworkMonitor(QObject):
    """网络监控器"""
    network_status = Signal(bool)  # True=网络正常, False=网络异常

    def __init__(self, handler: ProtocolHandler, check_interval: int = 60):
        super().__init__()
        self.handler = handler
        self.check_interval = check_interval
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            try:
                status = self.handler.check_online()
                self.network_status.emit(status)
            except Exception:
                self.network_status.emit(False)
            time.sleep(self.check_interval)


class NetworkLoginApp(QMainWindow):
    """主应用程序"""

    login_result = Signal(str, bool)  # message, success

    def __init__(self):
        super().__init__()

        self.config_manager = ConfigManager("config/network_config.yaml")
        self.config = self.config_manager.load_or_create()

        # 加载插件
        self.plugin_loader = PluginLoader("plugins")
        self.plugins = self.plugin_loader.load_all()

        # 获取全局设置
        settings = self.config_manager.get_global_settings()
        self.auto_reconnect = settings.get('auto_reconnect', True)
        self.check_interval = settings.get('check_interval', 60)
        self.periodic_login_interval = settings.get('periodic_login_interval', 0)
        self.periodic_login_enabled = settings.get('periodic_login_enabled', False)
        self.forced_auto_reconnect = settings.get('forced_auto_reconnect', False)
        self.forced_periodic_login = settings.get('forced_periodic_login', False)
        self.current_plugin_name = settings.get('current_plugin', 'portal')

        # 创建协议处理器
        self.handler: ProtocolHandler | None = None
        self._create_handler()

        # 初始化 UI
        self.init_ui()

        # 创建系统托盘
        self.create_system_tray()

        # 启动网络监控
        self.start_network_monitor()

        # 启动定期登录定时器
        self.start_periodic_login_timer()

        # 更新状态显示（必须在创建托盘后调用）
        self.update_status_display()

        # 配置文件监控（热更新）
        self.config_last_modified = os.path.getmtime(self.config_manager.config_path)
        self.config_monitor_timer = QTimer()
        self.config_monitor_timer.timeout.connect(self.check_config_update)
        self.config_monitor_timer.start(2000)

    def _create_handler(self):
        """创建当前插件的协议处理器

        bind_ip 由插件自己从配置中读取并管理，主程序不干预。
        """
        plugin = self.plugin_loader.get_plugin_by_id(self.current_plugin_name)
        if plugin:
            settings = self.config_manager.get_global_settings()
            plugin_config = self.config_manager.get_plugin_config(plugin.plugin_id)
            # bind_ip 由插件自己管理，传入 None 让插件自行决定
            self.handler = plugin.create_handler(settings, plugin_config, None)
            print(f"[App] 已创建处理器: {plugin.name} (ID: {plugin.plugin_id})")
        else:
            self.handler = None
            print(f"[App] 未找到插件 ID: {self.current_plugin_name}")

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("AutoNetworkLogin")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局：Splitter + 左侧树 + 右侧堆栈
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ===== 左侧：树形导航 =====
        tree_widget = QTreeWidget()
        tree_widget.setHeaderHidden(True)
        tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # 通用设置节点
        general_item = QTreeWidgetItem(tree_widget, ["通用设置"])
        general_item.setExpanded(True)

        basic_item = QTreeWidgetItem(general_item, ["基本设置"])
        basic_item.setData(0, Qt.ItemDataRole.UserRole, "general_settings")

        # 插件节点
        plugins_item = QTreeWidgetItem(tree_widget, ["插件"])
        plugins_item.setExpanded(True)

        for plugin in self.plugins:
            plugin_tree_item = QTreeWidgetItem(plugins_item, [plugin.name])
            plugin_tree_item.setData(0, Qt.ItemDataRole.UserRole, ("plugin", plugin.plugin_id))

        tree_widget.addTopLevelItem(general_item)
        tree_widget.addTopLevelItem(plugins_item)

        tree_widget.currentItemChanged.connect(self.on_tree_item_changed)

        # ===== 右侧：堆栈页面 =====
        self.stack = QStackedWidget()

        # 通用设置页面
        self.general_settings_page = self._create_general_settings_page()
        self.stack.addWidget(self.general_settings_page)

        # 插件配置页面（动态创建，用 plugin_id 作为 key）
        self.plugin_pages = {}
        for plugin in self.plugins:
            plugin_config = self.config_manager.get_plugin_config(plugin.plugin_id)
            widget = plugin.create_config_widget(plugin_config, self.config_manager.config_path)
            self.stack.addWidget(widget)
            self.plugin_pages[plugin.plugin_id] = widget

        # 默认显示通用设置
        self.stack.setCurrentIndex(0)

        # 将树和堆栈加入 splitter
        main_splitter.addWidget(tree_widget)
        main_splitter.addWidget(self.stack)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)

        # 中央布局
        layout = QVBoxLayout(central_widget)
        layout.addWidget(main_splitter)

        # 隐藏窗口（托盘运行）
        self.hide()

    def _create_general_settings_page(self) -> QWidget:
        """创建通用设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        # 状态显示
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 正在初始化...")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # 控制按钮
        button_layout = QHBoxLayout()
        button_layout.setAlignment(Qt.AlignLeft)

        self.login_btn = QPushButton("立即登录")
        self.login_btn.clicked.connect(self.manual_login)
        button_layout.addWidget(self.login_btn)

        self.auto_reconnect_cb = QCheckBox("自动重连")
        self.auto_reconnect_cb.setChecked(self.auto_reconnect)
        self.auto_reconnect_cb.stateChanged.connect(self.toggle_auto_reconnect)
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setEnabled(False)
        button_layout.addWidget(self.auto_reconnect_cb)

        self.periodic_login_cb = QCheckBox("定期登录")
        self.periodic_login_cb.setChecked(self.periodic_login_enabled)
        self.periodic_login_cb.stateChanged.connect(self.toggle_periodic_login)
        if self.forced_periodic_login:
            self.periodic_login_cb.setEnabled(False)
        button_layout.addWidget(self.periodic_login_cb)

        layout.addLayout(button_layout)

        # 配置管理按钮
        config_button_layout = QHBoxLayout()

        self.reload_config_btn = QPushButton("重新加载配置")
        self.reload_config_btn.clicked.connect(self.reload_config)
        config_button_layout.addWidget(self.reload_config_btn)

        self.hot_reload_cb = QCheckBox("自动热更新配置")
        self.hot_reload_cb.setChecked(True)
        self.hot_reload_cb.stateChanged.connect(self.toggle_hot_reload)
        config_button_layout.addWidget(self.hot_reload_cb)

        layout.addLayout(config_button_layout)

        # 间隔设置
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

        periodic_login_layout = QHBoxLayout()
        periodic_login_layout.addWidget(QLabel("定期登录间隔(秒):"))
        self.periodic_interval_spin = QSpinBox()
        self.periodic_interval_spin.setRange(0, 86400)
        self.periodic_interval_spin.setSpecialValueText("关闭")
        self.periodic_interval_spin.setValue(self.periodic_login_interval)
        self.periodic_interval_spin.valueChanged.connect(self.update_periodic_login_interval)
        periodic_login_layout.addWidget(self.periodic_interval_spin)
        periodic_login_layout.addStretch()
        interval_layout.addLayout(periodic_login_layout)

        layout.addLayout(interval_layout)

        # 当前插件选择
        plugin_layout = QHBoxLayout()
        plugin_layout.addWidget(QLabel("当前协议插件:"))

        self.plugin_combo = QComboBox()
        for plugin in self.plugins:
            self.plugin_combo.addItem(plugin.name, plugin.plugin_id)

        idx = self.plugin_combo.findData(self.current_plugin_name)
        if idx >= 0:
            self.plugin_combo.setCurrentIndex(idx)
        self.plugin_combo.currentTextChanged.connect(self.on_plugin_changed)

        plugin_layout.addWidget(self.plugin_combo)
        plugin_layout.addStretch()
        layout.addLayout(plugin_layout)

        # 日志显示
        layout.addWidget(QLabel("运行日志:"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        layout.addWidget(self.log_text)

        # 文件信息
        file_info_label = QLabel(f"配置文件: {self.config_manager.config_path}")
        file_info_label.setStyleSheet("color: gray;")
        layout.addWidget(file_info_label)

        return page

    def on_tree_item_changed(self, current, previous):
        """树形导航切换事件"""
        if current is None:
            return

        user_data = current.data(0, Qt.ItemDataRole.UserRole)
        if user_data == "general_settings":
            self.stack.setCurrentIndex(0)
        elif isinstance(user_data, tuple) and user_data[0] == "plugin":
            plugin_id = user_data[1]
            if plugin_id in self.plugin_pages:
                for i in range(self.stack.count()):
                    if self.stack.widget(i) is self.plugin_pages[plugin_id]:
                        self.stack.setCurrentIndex(i)
                        break

    def on_plugin_changed(self, plugin_id):
        """切换当前协议插件"""
        if plugin_id == self.current_plugin_name:
            return

        self.current_plugin_name = plugin_id
        self.config_manager.get_global_settings()['current_plugin'] = plugin_id
        self.config_manager.save()

        # 销毁旧 handler，创建新 handler（同时更新 bind_ip）
        self.handler = None
        self._create_handler()

        # 重启监控和定时器
        if hasattr(self, 'monitor'):
            self.monitor.stop()
        self.start_network_monitor()
        self.start_periodic_login_timer()

        self.log(f"已切换协议插件: {plugin_id}")
        self.update_status_display()

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

        reload_action = QAction("重新加载配置", self)
        reload_action.triggered.connect(self.reload_config)
        tray_menu.addAction(reload_action)

        tray_menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.update_tray_icon()
        self.tray_icon.show()

    def update_tray_icon(self):
        """更新托盘图标（不显示网卡信息）"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.auto_reconnect and self.periodic_login_enabled:
            color = QColor(0, 255, 0)
            tooltip_status = "自动重连+定时登录"
        elif self.auto_reconnect or self.periodic_login_enabled:
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
        self.tray_icon.setToolTip(f"网络登录工具 [{tooltip_status}]")

    def update_status_display(self):
        """更新状态显示（网卡状态由插件自己管理，不在主程序显示）"""
        parts = []

        if self.forced_auto_reconnect:
            parts.append("<font color='darkgreen'><b>自动重连</b></font>")
        elif self.auto_reconnect:
            parts.append("<font color='green'>自动重连[开启]</font>")
        else:
            parts.append("<font color='red'>自动重连[关闭]</font>")

        if self.periodic_login_enabled:
            parts.append("<font color='green'>定时登录[开启]</font>")
        else:
            parts.append("<font color='red'>定时登录[关闭]</font>")

        parts.append(f"<font color='blue'>插件[{self.current_plugin_name}]</font>")

        self.status_label.setText("状态: " + " | ".join(parts))
        self.update_tray_icon()

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()

    def start_network_monitor(self):
        """启动网络监控"""
        if self.handler is None:
            self.log("警告：无可用协议处理器，无法启动监控")
            return

        self.monitor = NetworkMonitor(self.handler, self.check_interval)
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
        if self.periodic_login_enabled and self.periodic_login_interval > 0:
            self.periodic_login_timer.start(self.periodic_login_interval * 1000)
            self.log(f"定期登录已启用，间隔: {self.periodic_login_interval}秒")
        else:
            self.periodic_login_timer.stop()
            self.log("定期登录已关闭")
        self.update_status_display()

    def periodic_login(self):
        """定期登录"""
        if not self.periodic_login_enabled:
            return
        self.log(f"执行定期登录（间隔: {self.periodic_login_interval}秒）...")
        self.do_login()

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
        if self.handler is None:
            self.log("错误：无可用协议处理器")
            return

        self.login_result.connect(self.on_login_result, Qt.ConnectionType.UniqueConnection)
        worker_thread = threading.Thread(target=self._do_login_worker, daemon=True)
        worker_thread.start()

    def _do_login_worker(self):
        """登录工作线程"""
        try:
            success, message = self.handler.login()
            self.login_result.emit(message, success)
        except Exception as e:
            self.login_result.emit(f"错误: {str(e)}", False)
        finally:
            try:
                self.login_result.disconnect(self.on_login_result)
            except Exception:
                pass

    def on_login_result(self, message, success):
        """登录结果处理"""
        if success:
            self.log(f"✓ {message}")
            self.tray_icon.showMessage("登录成功", message,
                                       QSystemTrayIcon.Information, 3000)
        else:
            self.log(f"✗ {message}")
            self.tray_icon.showMessage("登录失败", message,
                                       QSystemTrayIcon.Warning, 5000)

    def toggle_auto_reconnect(self, checked=None):
        """切换自动重连"""
        if self.forced_auto_reconnect:
            self.auto_reconnect_cb.setChecked(True)
            return

        if isinstance(checked, bool):
            self.auto_reconnect = checked
        else:
            self.auto_reconnect = self.auto_reconnect_cb.isChecked()

        self.config_manager.get_global_settings()['auto_reconnect'] = self.auto_reconnect
        self.config_manager.save()

        status = "开启" if self.auto_reconnect else "关闭"
        self.log(f"自动重连已{status}")
        self.update_status_display()

    def toggle_periodic_login(self, checked=None):
        """切换定期登录"""
        if self.forced_periodic_login:
            self.periodic_login_cb.setChecked(True)
            return

        if isinstance(checked, bool):
            is_enabled = checked
        else:
            is_enabled = self.periodic_login_cb.isChecked()

        self.periodic_login_enabled = is_enabled

        if is_enabled and self.periodic_login_interval == 0:
            self.periodic_login_interval = 600
            self.periodic_interval_spin.setValue(600)

        settings = self.config_manager.get_global_settings()
        settings['periodic_login_enabled'] = self.periodic_login_enabled
        settings['periodic_login_interval'] = self.periodic_login_interval
        self.config_manager.save()

        self.start_periodic_login_timer()

        status = "开启" if self.periodic_login_enabled else "关闭"
        self.log(f"定期登录已{status}")
        self.update_status_display()

    def update_check_interval(self, interval):
        """更新检查间隔"""
        self.check_interval = interval
        self.config_manager.get_global_settings()['check_interval'] = interval
        self.config_manager.save()
        self.log(f"网络检查间隔已更新为 {interval} 秒")

    def update_periodic_login_interval(self, interval):
        """更新定期登录间隔"""
        self.periodic_login_interval = interval
        self.config_manager.get_global_settings()['periodic_login_interval'] = interval

        if interval == 0:
            self.periodic_login_enabled = False
            self.periodic_login_cb.setChecked(False)

        self.config_manager.save()

        if interval > 0:
            self.log(f"定期登录间隔已更新为 {interval} 秒")
        else:
            self.log("定期登录已关闭")

        self.update_periodic_timer()

    def reload_config(self):
        """重新加载配置"""
        try:
            self.config = self.config_manager.reload()

            settings = self.config_manager.get_global_settings()
            self.auto_reconnect = settings.get('auto_reconnect', True)
            self.check_interval = settings.get('check_interval', 60)
            self.periodic_login_interval = settings.get('periodic_login_interval', 0)
            self.periodic_login_enabled = settings.get('periodic_login_enabled', False)
            self.forced_auto_reconnect = settings.get('forced_auto_reconnect', False)
            self.forced_periodic_login = settings.get('forced_periodic_login', False)
            self.current_plugin_name = settings.get('current_plugin', 'portal')

            if self.forced_auto_reconnect:
                self.auto_reconnect_cb.setEnabled(False)
            else:
                self.auto_reconnect_cb.setEnabled(True)

            if self.forced_periodic_login:
                self.periodic_login_cb.setEnabled(False)
            else:
                self.periodic_login_cb.setEnabled(True)

            self.auto_reconnect_cb.setChecked(self.auto_reconnect)
            self.periodic_login_cb.setChecked(self.periodic_login_enabled)
            self.interval_spin.setValue(self.check_interval)
            self.periodic_interval_spin.setValue(self.periodic_login_interval)

            self.update_periodic_timer()
            self.update_status_display()

            # 刷新插件下拉框
            idx = self.plugin_combo.findData(self.current_plugin_name)
            if idx >= 0:
                self.plugin_combo.setCurrentIndex(idx)

            self.log("配置文件已重新加载")
            self.tray_icon.showMessage("配置更新", "配置文件已重新加载",
                                       QSystemTrayIcon.Information, 3000)

        except Exception as e:
            self.log(f"重新加载配置文件失败: {str(e)}")
            QMessageBox.warning(self, "配置加载错误", str(e))

    def toggle_hot_reload(self, state):
        """切换热更新"""
        if self.hot_reload_cb.isChecked():
            self.config_monitor_timer.start(2000)
            self.log("配置文件热更新已启用")
        else:
            self.config_monitor_timer.stop()
            self.log("配置文件热更新已禁用")

    def check_config_update(self):
        """检查配置更新"""
        if self.config_manager.check_update():
            self.log("检测到配置文件已修改，正在重新加载...")
            self.reload_config()

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
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = NetworkLoginApp()

    window.tray_icon.showMessage("网络登录工具", "程序已启动并在系统托盘中运行",
                                 QSystemTrayIcon.Information, 3000)
    window.log("网络登录工具已启动")
    window.log(f"配置文件: {window.config_manager.config_path}")
    window.log(f"插件目录: plugins/")
    window.log(f"已加载插件数: {len(window.plugins)}")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
