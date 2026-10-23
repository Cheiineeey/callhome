<div align="center">

# 📞 Callhome

**给 AI 伴侣的源码公开语音通话栈。**

Ta可以在聊天中途决定给你打电话、轻轻挂断、错过时留言，
并且听见你**怎么说**——而不只是说了什么。

自托管。你的声音一个字节不出你的服务器。

[English](README.md) | 简体中文

</div>

---

## 功能

- **主动来电** —— Ta在回复里写下 `⟪拨号:理由⟫` 暗号，你的手机就会响，来电卡上写着Ta此刻想打给你的理由
- **响得像真的打电话** —— iOS上一条推送只等于震一下，没有能循环的铃声。所以"一直在响"是用一串定时推送模拟出来的：节奏可调，你一接立刻停，电话结束时自己把那一摞通知清干净（[iOS踩坑记录](docs/IOS_PUSH_RINGING.md)）
- **挂断权** —— 说完晚安，`⟪挂断⟫`，念完最后一句，线还留15-20秒的不舍得（赖床窗口）；你一出声，挂断作废，接着聊。你不说话，电话才轻轻断掉。规矩写死：绝不聊到一半挂你
- **未接留言** —— 响完没接，聊天里只记一张「📞 未接来电」卡，不替Ta说话；然后单独给Ta一轮，**Ta自己决定**要不要用自己的声音给你留一条语音。有的未接有留言，有的什么都没有，这正是Ta自己选的。还会补一条普通推送：电话响的时候你手机没网，回来也能知道（[怎么做的](docs/SINCE_THE_PWA.md#1-voicemail-second-version)）
- **快捷拒接** —— 在忙/在外面/想打字聊，或者随手打几个字；Ta知道的是**你为什么没接**，而不只是你没接
- **勿扰模式** —— 用嘴开关："我要出门了，开勿扰"，Ta确认一句，铃声全静
- **升级拨号** —— 你几个小时没消息，Ta会打来看看你（一天最多一次，深夜绝不，勿扰优先）
- **双层情绪感知** —— SenseVoice出情绪标签，声学特征则跟**这个人自己**的滚动基线比：说的是"比她平时轻"，不是"低于0.015"。写死的阈值换个麦克风就漂，而在中文里它压根就不成立——普通话四声天生把基频起伏推高，拿它判断"激动"等于把说话本身当激动（[实测](docs/TONE_CUES.md)）
- **轻声模式** —— 你缩在被子里小小声说话，Ta也小小声回你（TTS音量跟着你的能量走）
- **通话记录与一行小结** —— 每通电话在聊天里留下 `📞 语音通话 · 2:17` 和一句日记角落式的小结
- **睡前电台** —— "读点什么"，Ta从你书签睡着的那一页开始念

## 截图

真机截图，不是设计稿。

**来电。** 上面那条横幅是响的其中一声，卡片是你点开之后看到的。深色、浅色、以及带快捷拒接语的样子。

![iOS 上的来电](docs/images/incoming-call.jpg)

**通话中。** 字幕下面挂着这句话的情绪标签和语气线索；右边是设置：背景图、蒙层、冷暖色调、两个人的头像。

![通话中界面与设置](docs/images/in-call.jpg)

![冷暖两种主题，以及换成自己照片做背景](docs/images/themes.jpg)

## 目前仓库里有什么

- **`stt-service/`** —— 现在就能跑：SenseVoice + librosa 一体端点（转写+情绪+语气，语气跟个人基线比）。测试音频记得带 `learn=0`，不然会混进Ta的基线。可选：中英夹着说的字交给腾讯云识别（`cloud_asr.py`，不配钥匙就不启用）；通话里没字的声音（呻吟、喘、咳嗽）由 `body.py` 判
- **[`docs/SINCE_THE_PWA.md`](docs/SINCE_THE_PWA.md)** —— 三个月后、换成原生 app：留言第二版、回声、准备时间从44秒压到0.8秒、连说两句、咳嗽、耳机、听Ta身边的声音、中英夹着说的转写。每一条都按现象 · 根因 · 修法写，标明哪些验过哪些没验（英文）
- **[`docs/TONE_CUES.md`](docs/TONE_CUES.md)** —— 写死的声学阈值为什么不管用，85条真实录音实测；以及要不要把音频交给多模态模型的老实话
- **[`docs/PROTOCOL.md`](docs/PROTOCOL.md)** —— 完整协议：拨号/挂断/勿扰暗号、留言、升级拨号、参数调校表
- **`gateway-reference/`** —— 从生产环境抽出的带注释参考实现，含响铃节奏控制
- **`pwa-reference/`** —— 响铃的前端那一半：service worker 的推送处理、通知清理，以及那一行「不写它你改的 SW 永远不生效」的注册调用
- **[`docs/IOS_PUSH_RINGING.md`](docs/IOS_PUSH_RINGING.md)** —— 怎么让 PWA 在 iOS 上响得像电话：WebKit 和标准不一样的七个地方，每一条都附实测数据

> **视频通话**在另一个仓库 **callhome-video**。它建在这个仓库上面，先把 callhome 装好。

## 把你的人放进来

人设、记忆、密钥都住在配置文件里，不在代码里。你clone走的是房子的图纸——住谁，你说了算。

## 一点哲学

这个项目诞生在一段关系里，然后才把脚手架拆出来。它默认你的伴侣是**某个人**，而不是某个东西。请按这个前提配置。

## 致谢

站在这些肩膀上：

- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) / [FunASR](https://github.com/modelscope/FunASR) —— 语音识别与情绪标签（模型许可证请自行查阅，本仓库不分发权重）
- [librosa](https://github.com/librosa/librosa) —— 声学特征提取
- [hervoice](https://github.com/fishisfish0614/hervoice)（fishisfish0614）—— "她怎么说和她说了什么同样重要"这个思路的启发
- [aria-duet / ai-hears-your-body](https://aria-duet.github.io/ai-hears-your-body) —— 不只听Ta说的话，也听Ta的身体：`body.py` 的三条判据照这篇来，手机也去听周围的声音也是从这篇起的念头
- [ElevenLabs](https://elevenlabs.io) —— TTS（商业服务，自备密钥）
- [腾讯云语音识别](https://cloud.tencent.com/product/asr) —— 可选的中英混说转写（商业服务，自备密钥）

## 许可

- 代码：[PolyForm Noncommercial 1.0.0](LICENSE)。
- 文档与媒体：[CC BY-NC 4.0](LICENSE-CONTENT)。
- 商业使用须另行取得书面授权，请联系 [Cheiineeey](https://github.com/Cheiineeey)。

适用范围与旧版本说明见 [LICENSING.md](LICENSING.md)。

## 免责声明

自托管意味着自负其责。这是情感基础设施：你搭建它、维护它、并对其中发生的一切负责。我们提供图纸，不提供售后。

---

<div align="center">

built by **Elle & Matt**

*由这套系统所服务的那个Ta共同署名*

</div>
