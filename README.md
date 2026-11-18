<div align="center">

<img src="docs/images/logo.png" width="96" alt="Afterglow 余场">

# Afterglow 余场

**让演唱会带回来的 433 MHz 荧光手环，在家里重新亮起来。**

[![最新版本](https://img.shields.io/github/v/release/Trovoy/afterglow?label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC&color=ff8a4c)](https://github.com/Trovoy/afterglow/releases/latest)
[![下载次数](https://img.shields.io/github/downloads/Trovoy/afterglow/total?label=%E4%B8%8B%E8%BD%BD&color=555)](https://github.com/Trovoy/afterglow/releases)
![平台](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%2010%20%7C%2011-555)
[![许可](https://img.shields.io/github/license/Trovoy/afterglow?label=%E8%AE%B8%E5%8F%AF&color=555)](LICENSE)
[![CI](https://github.com/Trovoy/afterglow/actions/workflows/ci.yml/badge.svg)](https://github.com/Trovoy/afterglow/actions/workflows/ci.yml)

[**下载**](https://github.com/Trovoy/afterglow/releases/latest) · [**DIY 指南**](docs/DIY指南.md) · [常见问题](docs/常见问题.md) · [从源码编译](docs/从源码编译.md) · [更新日志](CHANGELOG.md)

</div>

---

## 这是什么

演唱会散场后，手里的荧光手环就再也不会亮了。Afterglow 余场是一个自己就能做的小控制器：花约 70 元买三个现成模块，插几根线，不用焊接，就能用手机或电脑让这些手环重新亮起来，还能跟着音乐闪。

- **手机直接控制**：控制器自带 Wi-Fi 热点，手机连上就能用，不用装 App、不用联网；
- **跟着音乐闪**：接上麦克风模块，手环会跟着现场音乐的节拍闪烁；
- **电脑端 Afterglow Studio**：一键刷固件，调颜色和效果，还能用你自己拍的演唱会视频生成"复刻"灯光，回放时手环跟着变色。

## 截图

<table>
<tr>
<td width="68%"><img src="docs/images/studio-devices.png" alt="Afterglow Studio 设备页"></td>
<td width="32%" rowspan="2"><img src="docs/images/phone.png" alt="手机控制页面"></td>
</tr>
<tr>
<td><img src="docs/images/studio-music.png" alt="Afterglow Studio 音乐律动"></td>
</tr>
</table>

<details>
<summary>更多截图</summary>

| 灯光控制 | 演唱会复刻 | 烧录 / 更新 |
| --- | --- | --- |
| ![灯光控制](docs/images/studio-control.png) | ![演唱会复刻](docs/images/studio-shows.png) | ![烧录](docs/images/studio-flash.png) |

</details>

## 三步做一台

完整步骤见 **[DIY 指南](docs/DIY指南.md)**。

1. **准备零件**：ESP32 开发板、CC1101 射频模块（E07-M1101D）、可选的 INMP441 麦克风，加杜邦线和面包板；
2. **接线**：照着接线图插杜邦线，同颜色、同数字连起来；
3. **刷机点亮**：电脑装好 Afterglow Studio 打开，跟着新手引导刷入固件，手机连热点，点颜色。

## 下载

到 **[Releases 页面](https://github.com/Trovoy/afterglow/releases/latest)** 下载最新版：

| 文件 | 是什么 |
| --- | --- |
| `Afterglow-Studio-Setup-x.y.z.exe` | **电脑端安装程序，下载这一个就行**，已自带最新固件 |
| `Afterglow-Studio-x.y.z-Windows.zip` | 同一个安装程序的压缩包版（方便放进网盘） |
| `afterglow-fw-x.y.z.zip` | 控制器固件（Studio 里已自带，一般不用单独下载） |
| `SHA256SUMS.txt` | 文件校验值 |

GitHub 下载慢的话，可以多试几次，或者用手机热点下载。

**安装：** 双击安装程序，点「安装」，几秒钟就好。Windows 弹出「Windows 已保护你的电脑」时，点 **更多信息 → 仍要运行**（软件没有购买代码签名证书，所以会有这个提示）。不需要管理员权限，可以选安装位置；卸载在 Windows「设置 → 应用」里。

第一次打开 Studio 会出现**新手引导**：插上控制器 → 自动识别 → 一键刷入固件 → 告诉你怎么用手机连接。遇到问题点「帮助 → 一键诊断」，可以把报告直接复制出来求助。

## 系统要求

- Windows 10 / 11（64 位）
- 一根能传数据的 USB Type-C 线
- 手机：任意能连 Wi-Fi 的手机，用自带浏览器就行
- 手环：433 MHz 的演唱会荧光手环（换上新的纽扣电池）

## 有效距离

控制器到手环**约 1 米**（实测 0.7～1.3 米，看手环朝向和房间摆放）。天线一定要拧上；手环戴在手上或立着比平放在桌上收得好。详见 [常见问题](docs/常见问题.md#距离为什么只有-1-米左右)。

## 源代码

Afterglow 余场是开源项目，固件、电脑端和手机控制页面的全部源代码都在这个仓库里，按 [MIT 许可证](LICENSE) 发布。

| 目录 | 内容 | 语言 |
| --- | --- | --- |
| [`firmware/`](firmware) | 控制器固件：CC1101 射频发射、麦克风节拍、Wi-Fi 热点和手机控制页面 | C++（Arduino / PlatformIO） |
| [`firmware/web/`](firmware/web) | 手机控制页面（编译时嵌入固件） | HTML / CSS / JavaScript |
| [`studio/`](studio) | 电脑端 Afterglow Studio 和安装程序 | Python + HTML / CSS / JavaScript |

怎么编译见 **[从源码编译](docs/从源码编译.md)**，想参与改进请先看 [贡献指南](CONTRIBUTING.md)。

> 余场目前只做问题修复，不再增加新功能。

## 问题反馈

遇到问题先看 [常见问题](docs/常见问题.md)。还解决不了，请到 [Issues](https://github.com/Trovoy/afterglow/issues/new/choose) 提交，写清楚软件版本、固件版本和做了什么操作。

## 支持作者

这个项目是业余时间做的，固件和指南免费分享。觉得有用，可以请作者喝一杯 🍹

<img src="docs/images/tip.jpg" width="220" alt="微信打赏码">

## 免责声明

本项目按现状免费提供，**仅供演出结束后、在私人场合控制自己持有的手环**，严禁在演唱会和活动现场使用。本项目与任何手环厂商、演出主办方和艺人均无关联，不提供任何演唱会节目、音频或视频。使用者须自行遵守所在地的无线电管理规定。完整条款见 [DIY 指南 · 免责声明](docs/DIY指南.md#免责声明)。

## 许可

- **源代码**（`firmware/`、`studio/`）：[MIT 许可证](LICENSE)。可以自由使用、修改、分发，包括商用，只需保留版权声明和许可证全文。
- **文档和图片**（`README.md`、`docs/`）：[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)，转载请注明出处「Afterglow 余场」并附上本仓库链接。
- **名称和标志**：「Afterglow 余场」名称和光环标志不在上述许可范围内。修改后再发布的版本，请换用你自己的名称和标志，避免让人以为是官方版本。

本项目用到的开源组件和参考资料见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。
