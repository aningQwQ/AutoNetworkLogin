"""插件加载器 - 扫描 plugins/ 目录，动态加载所有插件"""
import os
import sys
import importlib.util
from typing import List

from plugin_base import ProtocolPlugin


class PluginLoader:
    """插件加载器

    功能：
    - 扫描 plugins/ 目录
    - 动态导入所有 .py 文件
    - 提取 ProtocolPlugin 子类实例
    - 返回插件列表
    """

    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self._plugins: List[ProtocolPlugin] = []

    def load_all(self) -> List[ProtocolPlugin]:
        """加载所有插件

        Returns:
            所有插件实例列表
        """
        self._plugins = []

        if not os.path.exists(self.plugins_dir):
            print(f"[PluginLoader] 插件目录不存在: {self.plugins_dir}")
            return self._plugins

        for filename in os.listdir(self.plugins_dir):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue

            filepath = os.path.join(self.plugins_dir, filename)
            try:
                module_name = f"plugins.{filename[:-3]}"
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 查找模块中的 Plugin 类（必须是 ProtocolPlugin 的子类）
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, ProtocolPlugin) and
                            attr is not ProtocolPlugin):
                        try:
                            plugin_instance = attr()
                            self._plugins.append(plugin_instance)
                            print(f"[PluginLoader] 已加载插件: {plugin_instance.name} (ID: {plugin_instance.plugin_id})")
                        except Exception as e:
                            print(f"[PluginLoader] 实例化插件 {attr_name} 失败: {e}")

            except Exception as e:
                print(f"[PluginLoader] 加载插件文件 {filename} 失败: {e}")

        return self._plugins

    def get_plugin_by_id(self, plugin_id: str) -> ProtocolPlugin | None:
        """根据 plugin_id 获取插件"""
        for plugin in self._plugins:
            if plugin.plugin_id == plugin_id:
                return plugin
        return None

    def get_plugin_by_name(self, name: str) -> ProtocolPlugin | None:
        """根据显示名获取插件"""
        for plugin in self._plugins:
            if plugin.name == name:
                return plugin
        return None

    @property
    def plugins(self) -> List[ProtocolPlugin]:
        return self._plugins
