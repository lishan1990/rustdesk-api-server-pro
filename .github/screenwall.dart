// RustDesk 屏幕墙模式（管理员专用监控墙）
// 主进程以 --screenwall 启动，读取 exe 同目录 screenwall.json，
// 开 N 个独立远程会话窗口，setFrame 摆成 N×N 宫格。点击任一窗口即可接管。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:desktop_multi_window/desktop_multi_window.dart';
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'main.dart' show initEnv;

class _SWDevice {
  final String id;
  final String name;
  final String password;
  _SWDevice(this.id, this.name, this.password);
  factory _SWDevice.fromJson(Map<String, dynamic> j) => _SWDevice(
        (j['id'] ?? '').toString(),
        (j['name'] ?? j['id'] ?? '').toString(),
        (j['password'] ?? '').toString(),
      );
}

/// 屏幕墙入口：由 main.dart 在 --screenwall 分支调用
/// 调用前 main() 已执行 WidgetsFlutterBinding.ensureInitialized()
Future<void> runScreenWall() async {
  try {
    // 完整初始化 FFI（与 runMainApp 相同），保证子窗口会话可用
    await initEnv('main');
    await windowManager.ensureInitialized();

    // 配置文件：exe 当前工作目录下的 screenwall.json
    final cfgPath = '${Directory.current.path}${Platform.pathSeparator}screenwall.json';
    final content = await File(cfgPath).readAsString();
    final cfg = jsonDecode(content) as Map<String, dynamic>;
    final layout = (cfg['layout'] ?? '3x3').toString();
    final parts = layout.split('x');
    int cols = int.tryParse(parts[0]) ?? 3;
    int rows = int.tryParse(parts.length > 1 ? parts[1] : '3') ?? 3;
    if (cols < 1 || cols > 6) cols = 3;
    if (rows < 1 || rows > 6) rows = 3;

    final devices = <_SWDevice>[];
    for (final d in (cfg['devices'] as List? ?? [])) {
      final dev = _SWDevice.fromJson(d as Map<String, dynamic>);
      if (dev.id.isNotEmpty) devices.add(dev);
    }
    if (devices.isEmpty) throw 'no devices in screenwall config';

    // 屏幕物理尺寸 / DPR → 逻辑像素
    final ui.FlutterView view = ui.PlatformDispatcher.instance.views.first;
    final ui.Size ps = view.physicalSize;
    final double dpr = view.devicePixelRatio == 0 ? 1.0 : view.devicePixelRatio;
    final double sw = ps.width / dpr;
    final double sh = ps.height / dpr;
    final double cw = sw / cols;
    final double ch = sh / rows;
    debugPrint('screenwall: ${devices.length} devices, ${cols}x${rows}, cell ${cw.toInt()}x${ch.toInt()}, dpr=$dpr');

    // 隐藏主窗口，只显示宫格子窗口
    await windowManager.hide();

    int placed = 0;
    for (int i = 0; i < devices.length && i < cols * rows; i++) {
      final dev = devices[i];
      // type=1 = WindowType.RemoteDesktop（enum: Main=0, RemoteDesktop=1）
      final msg = jsonEncode(<String, dynamic>{
        'type': 1,
        'id': dev.id,
        'password': dev.password,
      });
      final controller = await DesktopMultiWindow.createWindow(msg);
      final int col = i % cols;
      final int row = i ~/ cols;
      controller
        ..setFrame(ui.Offset(col * cw, row * ch) & ui.Size(cw, ch))
        ..setTitle('${dev.name} (${dev.id})');
      placed++;
      debugPrint('screenwall: opened ${dev.name} -> window ${controller.windowId}');
      await Future<void>.delayed(const Duration(milliseconds: 350));
    }
    debugPrint('screenwall: $placed windows placed');
  } catch (e, st) {
    debugPrint('screenwall error: $e\n$st');
    try { await windowManager.show(); } catch (_) {}
  }
}
