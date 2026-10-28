
<div align="center">

# GLaDOS 自动签到⚡

_✨ 基于 [Python](https://www.python.org/) 实现的[GLaDOS](https://github.com/glados-network/GLaDOS)签到程序 ✨_  

</div>

<p align="center">
  <a href="https://github.com/hennessey-v/GlaDOS_Checkin_ql/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/hennessey-v/GlaDOS_Checkin_ql?color=%23ed793a" alt="license">
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="license">
  </a>
  <a href="https://github.com/hennessey-v/GlaDOS_Checkin_ql/">
    <img src="https://img.shields.io/github/stars/hennessey-v/GlaDOS_Checkin_ql?color=%2330c352" alt="license">
  </a>
</p>

## 项目特点

- 基于 [Python](https://www.python.org/)语言
- 可自定义签到时间（基于crontab）
- 支持多账户
- 支持本地部署
- 支持部署在[青龙面板](https://github.com/whyour/qinglong)
- 支持 GitHub Actions 自动化部署
- 支持独立通知服务模块
- [更新日志](#更新日志)

## 简单介绍一下GLaDOS

>GLaDOS是一家高速稳定的V2Ray/Trojan机场，超过4年的老品牌，官方网站使用自主开发的管理系统，属于技术派的老站，支持WireGuard协议加速，而且流量套餐性价比非常高。

GLaDOS家的优惠活动非常良心，新账号注册一段时间后基本都会赠送一次30天的基础套餐激活码，如果你的账户是教育版edu账户，甚至可以直接得到365天的基础套餐。不仅如此，每天签到也会获得一天当前套餐的续期，因此才有了本项目。

[GLaDOS 项目地址](https://github.com/glados-network/GLaDOS)

## 开始使用

### 新版会话更新（2026-10）

当前会话使用 `gld:sess` 和 `gld:sess.sig`。在 `https://glados.cloud` 登录后，
从 Network 中成功的 `/api/user/status` 请求复制完整 Cookie。不要把旧 `koa:` 改名。
后面的旧截图只用于说明取值位置。

Actions 会接收签到和状态响应中的会话 `Set-Cookie`，后续请求立即使用新值；
状态验证通过后，将更新后的全部账号加密写回原 Secret。无轮换时不改写 Secret。
这只能接收服务端主动更新的凭据，不能恢复已到期/被撤销的会话，也不保证超过 14 天仍有效。

在 Settings → Secrets and variables → Actions → **Secrets** 配置：

| 名称 | 配置 |
| --- | --- |
| `GR_COOKIE` | 每个账号一行完整 Cookie；兼容 `&` 分隔。推荐换行，以保留 Cookie 值内的 `&`。 |
| `GR_USER_AGENT` | 可选，生成会话的浏览器完整 UA。单行用于全部账号；不同浏览器按 Cookie 顺序每账号一行。未配置时沿用原默认 UA。 |
| `COOKIE_UPDATE_TOKEN` | 推荐，Fine-grained PAT 限定本仓库，授予 **Secrets: Read and write** 和 **Actions: Read**。 |
| `REPO_ACCESS_TOKEN` | 保留通知配置；未配置专用更新 Token 时也用于更新会话，原 classic PAT 的 `repo` 权限通常可用。 |
| `NOTIFICATION_REPO` | 保留通知服务仓库地址。 |

自动的 `GITHUB_TOKEN` 不能代替更新 Token。Token 放在 Secrets，不放在 Variables 或代码里。
脚本通过 runner 自带的 `gh` 加密上传，Cookie 走标准输入，不写命令行参数或临时文件。
新会话值注册为 Actions 日志掩码，只输出是否轮换及保存结果。

工作流排队执行，开始和保存前检查 Secret 更新时间。检测到手工更新时停止旧会话回写。
GitHub Secrets API 没有原子条件写入，运行期间请避免手工编辑 Secret；若已更新，等本次结束后重新运行。
`cookie1` 单账号兼容配置会写回 `cookie1`，配置了 `GR_COOKIE` 时优先使用后者。

Cookie 无效、设备不匹配、状态验证或保存失败都会使任务失败；部分账号失败时继续处理其余账号，
保留失败账号原值，并保存其他账号已验证的新会话。通知仍会收到具体失败信息。

本次自动持久化仅适配 GitHub Actions。本机/青龙检测到轮换时会提示重新获取并更新环境变量。
青龙同步还需下载同目录的 `session_cookies.py`。
实现参考：[zxc-1/Scripts 会话轮换修复](https://github.com/zxc-1/Scripts/pull/6)。

### 准备工作
<details>
<summary>账号的 cookie（并非仅此单一获取方式）</summary>

  1. 注册 [GLaDos](https://glados.rocks/) 并登陆。  
  （注册时可选填邀请码，双方都将获得微量的额外天数奖励。这一步并不重要，但我期待并感谢大家的支持）
   ```
   38JNV-P6O0T-XXC1F-CC3OI
   ```

  2. 在首页往下拉，找到 **我的会员 > 会员签到**

     ![checkin_entrance](assets/checkin_entrance.png)

  3. 点击跳转到签到页面

     ![checkin_page](assets/checkin_page.png)

  4. 打开 "开发者工具"，通常快捷键为 **F12**，或是点击 **浏览器选项 > 更多工具 > 开发者工具**，打开后如图所示点击 "**network**" 标签

     ![devtools](assets/devtools.png)

  5. 在签到页面点击签到，相对应的开发者工具 **network** 标签下会出现 "**checkin**" 请求，点击该请求，会出现更多信息，找到 "**Request Headers**" 里的 "**cookie**"，接下来设置密钥时需要用到

     ![cookie](assets/cookie.png)
</details>

### qinglong 部署 (推荐)

<details>
<summary>一、安装依赖</summary>

  - 打开青龙面板，依赖管理页面。切换到Python3模块，点击新建依赖，导入并安装依赖
  ```
  requests
  ```

  ![cookie](assets/lib.png)

</details>

<details>
<summary>二、在青龙面板中设置环境变量</summary>

- 名称填入 **GR_COOKIE**，值使用完整 Cookie，例如 `gld:sess=会话值; gld:sess.sig=签名值`。
- 多账号多次添加变量

![cookie](assets/GR_cookie.png)

</details>

<details>
<summary>三、在青龙中拉取本仓库</summary>

- 国内环境拉取指令（带代理）
```
ql repo https://ghproxy.com/https://github.com/Kevin589981/GlaDOS_Checkin_ql.git "checkin.py" "backUp|assets|README.md|test_checkin.py" "sendNotify.py|session_cookies.py"
```
- 国外环境拉取指令
```
ql repo https://github.com/Kevin589981/GlaDOS_Checkin_ql.git "checkin.py" "backUp|assets|README.md|test_checkin.py" "sendNotify.py|session_cookies.py"
```
</details>

<details>
<summary>四、运行脚本查看运行结果</summary>

![cookie](assets/push_detail.png)

</details>

### GitHub Actions 部署 (推荐)

<details>
<summary>一、Fork 本仓库</summary>

- 点击右上角的 Fork 按钮，将本仓库 Fork 到你的 GitHub 账户下

</details>

<details>
<summary>二、配置 GitHub Secrets</summary>

在你 Fork 的仓库中，进入 Settings > Secrets and variables > Actions，添加以下 Secrets：

**必需的 Secrets：**
- `GR_COOKIE`: GLaDOS 账户的完整 Cookie，需要包含 `gld:sess` 与 `gld:sess.sig`
  - 多账号可以用 `&` 或换行符分隔
- `REPO_ACCESS_TOKEN`: GitHub Personal Access Token，用于触发通知服务
  - 需要有 `repo` 权限
- `NOTIFICATION_REPO`: 通知服务仓库地址，格式为 `username/notification-service`

**可选的 Secrets（兼容旧版本）：**
- `cookie1`: 单个账户的 Cookie（如果设置了 GR_COOKIE 则优先使用 GR_COOKIE）
- 自动更新 Token、浏览器 UA 及权限说明见上方“新版会话更新”。

</details>

<details>
<summary>三、启用 GitHub Actions</summary>

- 进入你 Fork 的仓库，点击 Actions 标签页
- 如果看到提示需要启用 Actions，点击启用
- 工作流会在每天 UTC+8 07:00 附近自动运行，实际可能受 GitHub 调度延迟影响
- 你也可以在 Actions 页面手动触发运行

</details>

<details>
<summary>四、查看运行结果</summary>

- 在 Actions 页面可以查看每次运行的详细日志
- 签到完成后会自动触发通知服务发送通知

</details>

### 本机部署

<details>
<summary>一、拉取仓库到本地</summary>

- 国内环境拉取指令（带代理）
```
git clone https://ghproxy.com/https://github.com/hennessey-v/GlaDOS_Checkin_ql.git GlaDOS_Checkin
```
- 国外环境拉取指令
```
git clone https://github.com/hennessey-v/GlaDOS_Checkin_ql.git GlaDOS_Checkin
```
</details>

<details>
<summary>二、安装依赖</summary>

  - 进入项目目录输入以下命令
  - 国内环境
  ```
  pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```
  - 国外环境
  ```
  pip install -r requirements.txt
  ```
</details>

<details>
<summary>三、配置cookie</summary>

- 进入 GlaDOS_Checkin 文件夹，将cookie按照 **'koa:sess=xxxxxxxxx; koa:sess.sig=xxxx;'** 的格式填入 **config.py** ，多账号用 "," 分割
 ![cookie](assets/cookies.png)
</details>
<details>
<summary>四、运行脚本</summary>

- 在GlaDOS_Checkin目录下，运行脚本
```
python checkin.py
```

- linux可配和[crontab](https://www.runoob.com/linux/linux-comm-crontab.html)实现定时签到，windows可使用[go-crontab](https://github.com/hezhizheng/go-crontab/releases)来实现。具体用法请自行探索

</details>



## 更新日志
<details>
<summary>更新日志</summary>

### [1.2.4] - 2023-7.27
#### 变更
- 修复签到失败的问题

### [1.2.3] - 2023-7.26
#### 变更
- 文档增加安装依赖步骤

### [1.2.2] - 2023-7.21
#### 新增
- 新增飞书等多种通知方式

### [1.2.1] - 2023-5-7
#### 新增
- 新增本地部署
- 新增运行失败提示
#### 变更
- 优化运行中信息显示效果
- 完善文档

### [1.2.0] - 2023-03-22
#### 变更
- 优化逻辑，增强运行稳定性。
- 修复了空Cookie导致的报错。
- 完善注释，增强可读性。

### [1.1.2] - 2023-02-17
#### 变更
- 修复企业微信应用文本方式推送错误（感谢[肥牛（sailcom）](https://github.com/sailcom)）
- 文档小变化

### [1.1.1] - 2023-01-31
#### 新增
- 添加了国内环境下的拉取指令
- 新增问题模板

### [1.1.0] - 2023-01-29
#### 变更
- 修复拉取脚本无法自动添加任务的问题
- 文档更新

### [1.0.0] - 2023-01-12
项目发布
#### 变更
- 兼容多账户，推送信息增加账户邮箱信息提示
#### 新增
- 多账号签到
- 多种推送渠道
  - Bark服务
  - TGBot推送
  - QQ机器人
  - 企业微信应用
  - 企业微信BOT
  - 微信推送Plus+

</details>

## 鸣谢
- 部分程序代码来源于开源项目[glados_checkin](https://github.com/akinlau/glados_checkin)，部分图片素材来自于[DullSword](https://github.com/DullSword)大佬
- 问题模板灵感来自于开源项目[lx-music-desktop](https://github.com/lyswhut/lx-music-desktop)


## Star⭐

**如果你觉得这个项目还不错的话，可以支持一下点个 Star⭐.**


2025年09月28日20:37:23更新

2025年10月01日11:42:03更新

2025年11月01日11:42:12更新

2025年12月01日12:10:12更新

2026年01月01日12:08:51更新

2026年02月01日13:01:08更新

2026年03月01日12:53:28更新

2026年03月06日21:27:44更新

2026年04月01日13:24:29更新

2026年05月01日14:16:10更新

2026年06月01日16:34:24更新

2026年07月01日15:11:42更新

2026年08月01日13:54:07更新

2026年09月01日16:20:32更新

2026年10月01日17:48:33更新

