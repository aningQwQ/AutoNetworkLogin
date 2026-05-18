"""工具函数 - 从旧代码迁移，供插件使用"""
import socket
import psutil
from urllib.parse import urlparse


def get_network_interfaces() -> dict[str, str]:
    """获取所有网卡及其IP（跨平台，使用psutil）"""
    interfaces = {}
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip and not ip.startswith('127.'):
                        interfaces[iface] = ip
    except Exception:
        pass
    return interfaces


def send_http_via_socket(method: str, url: str, data=None, headers=None,
                         bind_ip: str = None, timeout: int = 10) -> tuple:
    """通过 socket 发送 HTTP 请求

    Args:
        method: HTTP 方法
        url: 完整 URL
        data: POST 数据
        headers: 请求头字典
        bind_ip: 绑定的源 IP
        timeout: 超时时间

    Returns:
        (status_code, response_body, response_headers)
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
        except ValueError:
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


def check_network_connectivity(test_url: str, bind_ip: str = None,
                                timeout: int = 5) -> bool:
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
    except Exception:
        return False
