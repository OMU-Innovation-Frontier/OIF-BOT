# OIF Bot デプロイ手順

## 1. Discord Developer Portal での設定

1. https://discord.com/developers/applications にアクセス
2. 「New Application」→ アプリ名を入力（例: OIF Bot）
3. 「Bot」タブ → 「Add Bot」
4. Token をコピーして保存（後で使う）
5. 以下の Privileged Gateway Intents を ON にする
   - SERVER MEMBERS INTENT
   - MESSAGE CONTENT INTENT
6. 「OAuth2」→「URL Generator」
   - Scopes: `bot`
   - Bot Permissions: `Manage Roles`, `Manage Nicknames`, `Send Messages`, `Read Message History`, `Add Reactions`
7. 生成されたURLでBotをサーバーに招待

---

## 2. Railwayへのデプロイ

### 2-1. GitHubにpush
```
oif_bot/
  ├── bot.py
  └── requirements.txt
```

### 2-2. Railway設定
1. https://railway.app → 「New Project」→「Deploy from GitHub repo」
2. リポジトリを選択
3. 「Variables」タブで環境変数を設定:

| Key | Value |
|-----|-------|
| `DISCORD_TOKEN` | BotのToken |
| `APPLICATION_CHANNEL_ID` | 申請チャンネルのID（数字） |

4. 「Settings」→ Start Command:
```
python bot.py
```

---

## 3. bot.py の設定を合わせる

`bot.py` の上部にある定数を自分のサーバーに合わせて変更:

```python
ROLE_NAMES = {
    "omu":      "OMU",        # ← サーバーの実際のロール名
    "external": "外部",
    "alumni":   "OB/OG",
    "pending":  "未認証",
}

ADMIN_ROLE_NAME = "OIF Core"   # ← 管理者ロール名
```

---

## 4. 既存メンバーへの一括ロール付与

1. `members_sample.csv` を参考にCSVを作成
2. user_id はDiscordで「開発者モード」をONにして、メンバーを右クリック→「IDをコピー」
3. Discordの任意のチャンネルで:
```
!bulk_assign
```
とCSVファイルを添付して送信

---

## 5. コマンド一覧

| コマンド | 説明 |
|---------|------|
| `!bulk_assign` + CSV添付 | 既存メンバー一括ロール付与 |
| `!assign @user omu 山田太郎 2 情報` | 個別に手動付与 |
| `!graduate @user` | OMU生 → OB/OGに移行 |

---

## 6. 申請チャンネルの運用

ピン留めするテンプレ:
```
【OIF 入会申請】
━━━━━━━━━━━━━━
名前：（ニックネーム可）
所属：OMU / 外部 / OB・OG
学年：（OMUのみ。例: 2）
学科：（OMUのみ。例: 情報）
興味：
━━━━━━━━━━━━━━

管理者がこのチャンネルのメッセージに ✅ をつけると自動でロール付与・ニックネーム変更されます。
❌ をつけると却下メッセージが送られます。
