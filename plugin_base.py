"""插件基类 - 定义所有插件必须实现的接口"""
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QWidget


class ProtocolPlugin(ABC):
    """插件基类：所有协议插件必须继承此类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """插件显示名称（UI 中显示）"""
        pass

    @property
    def plugin_id(self) -> str:
        """插件内部 ID（配置匹配用，默认取 name 的 ASCII 部分或全小写）"""
        # 默认行为：提取 name 中的英文部分，或全小写
        import re
        english_part = re.findall(r'[a-zA-Z]+', self.name)
        if english_part:
            return ''.join(english_part).lower()
        return self.name.lower().replace(' ', '_').replace('通用', '').replace('协议', '')

    @property
    @abstractmethod
    def description(self) -> str:
        """插件描述"""
        pass

    @abstractmethod
    def create_config_widget(self, plugin_config: dict, config_path: str) -> QWidget:
        """创建该插件的配置控件

        Args:
            plugin_config: 该插件的配置字典（可变引用，控件修改后直接写回）
            config_path: 配置文件路径

        Returns:
            QWidget: 配置界面控件
        """
        pass

    @abstractmethod
    def create_handler(self, global_settings: dict, plugin_config: dict, bind_ip: str):
        """创建该插件的协议处理器

        Args:
            global_settings: 全局设置字典
            plugin_config: 该插件的配置字典
            bind_ip: 绑定的网卡IP（None表示自动）

        Returns:
            ProtocolHandler: 协议处理器实例
        """
        pass


class ProtocolHandler(ABC):
    """协议处理器接口：实现具体的登录/登出/检测逻辑"""

    @abstractmethod
    def check_online(self) -> bool:
        """检测当前是否已在线/已登录

        Returns:
            True 表示已在线，False 表示未在线
        """
        pass

    @abstractmethod
    def login(self) -> tuple[bool, str]:
        """执行登录操作

        Returns:
            (success, message): 登录是否成功及消息
        """
        pass

    def logout(self) -> tuple[bool, str]:
        """执行登出操作（可选实现）

        Returns:
            (success, message): 登出是否成功及消息
        """
        return True, "登出功能未实现"
