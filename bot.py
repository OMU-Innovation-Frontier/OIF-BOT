import discord
from discord.ext import commands
import csv
import io
import os
import asyncio
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()

# ─────────────────────────────────────────
# 設定（環境変数 or 直接書き換え）
# ─────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")

# ロール名（サーバーの実際のロール名に合わせて変更）
# サーバー側でロール名を変えたら .env / Railway の Variables を直すだけで済むよう環境変数を優先する。
# 過去に ADMIN_ROLE_NAME がサーバーの実態とズレて承認が丸ごと無言で死んだため（2026-08 調査）。
ROLE_NAMES = {
    "omu":      os.getenv("ROLE_OMU", "OMU"),
    "external": os.getenv("ROLE_EXTERNAL", "外部"),
    "alumni":   os.getenv("ROLE_ALUMNI", "OB/OG"),
    "pending":  os.getenv("ROLE_PENDING", "未認証"),
}

# 申請チャンネルのID（Discordで右クリック→IDをコピー）
APPLICATION_CHANNEL_ID = int(os.environ.get("APPLICATION_CHANNEL_ID", 0))

# 承認リアクション
APPROVE_EMOJI = "✅"
REJECT_EMOJI  = "❌"

# 管理者ロール名（このロールを持つ人だけ承認できる）
ADMIN_ROLE_NAME = os.getenv("ROLE_ADMIN", "運営")

# ─────────────────────────────────────────
# Bot初期化
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────────
# ヘルパー関数
# ─────────────────────────────────────────
def get_role(guild: discord.Guild, key: str) -> discord.Role | None:
    name = ROLE_NAMES.get(key)
    return discord.utils.get(guild.roles, name=name)


def is_admin(member: discord.Member) -> bool:
    return any(r.name == ADMIN_ROLE_NAME for r in member.roles)


def parse_application(content: str) -> dict | None:
    """
    申請メッセージから情報をパース。
    フォーマット例:
      名前：山田太郎
      所属：OMU
      学年：2年
      学科：情報工
      興味：ML、AIツール、Kaggle、強化学習、AI全般など
    """
    result = {}
    for line in content.splitlines():
        # 全角コロン（：）または半角コロン（:）で分割し、前後の空白を除去
        if "：" in line:
            key, _, val = line.partition("：")
            result[key.strip()] = val.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()

    if "所属" not in result:
        return None
    return result


def format_nickname(name: str, grade: str, dept: str) -> str:
    """名前@[学年][学科] 形式に変換 (例: たぐ@B2情報工)"""
    grade_short = grade.replace("年", "").strip() if grade else ""
    # 学科名も2文字制限を外し、そのままor短縮して利用（32文字制限は後続で処理）
    dept_short = dept.strip() if dept else ""
    suffix = f"{grade_short}{dept_short}" if (grade_short or dept_short) else ""
    nick = f"{name}@{suffix}" if suffix else name
    return nick[:32]  # Discordのニックネーム上限


# ─────────────────────────────────────────
# イベント: 起動
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ OIF Bot 起動完了: {bot.user}")

    # 設定がサーバーの実態と合っているか起動時に必ず検証する。
    # ここを黙って通すと「Botは動いているのに何も起きない」状態になり、原因究明に時間を食う。
    for guild in bot.guilds:
        print(f"--- 設定チェック: {guild.name} ---")
        for key, name in ROLE_NAMES.items():
            if discord.utils.get(guild.roles, name=name) is None:
                print(f"  ❌ ロール「{name}」({key}) が存在しません。ROLE_{key.upper()} を修正してください")
        if discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME) is None:
            print(f"  ❌ 管理者ロール「{ADMIN_ROLE_NAME}」が存在しません。承認が全て無視されます（ROLE_ADMIN）")
        if guild.get_channel(APPLICATION_CHANNEL_ID) is None:
            print(f"  ❌ 申請チャンネル {APPLICATION_CHANNEL_ID} が見つかりません（APPLICATION_CHANNEL_ID）")
        if not guild.me.guild_permissions.manage_roles:
            print("  ❌ Manage Roles 権限がありません")
        if not guild.me.guild_permissions.manage_nicknames:
            print("  ❌ Manage Nicknames 権限がありません")


# ─────────────────────────────────────────
# イベント: 新規参加 → 未認証ロール自動付与
# ─────────────────────────────────────────
@bot.event
async def on_member_join(member: discord.Member):
    role = get_role(member.guild, "pending")
    if role:
        await member.add_roles(role)
        print(f"[入会] {member.display_name} に「未認証」を付与")


# ─────────────────────────────────────────
# イベント: 申請チャンネルのリアクション → ロール付与
# ─────────────────────────────────────────
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # 申請チャンネル以外は無視
    if payload.channel_id != APPLICATION_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    # ユーザーをキャッシュ、もしくはサーバーから再取得
    reactor = guild.get_member(payload.user_id)
    if not reactor:
        try:
            reactor = await guild.fetch_member(payload.user_id)
        except Exception:
            return

    # 管理者以外のリアクションは無視（✅/❌ のときだけ、なぜ無視したかを残す）
    if not reactor or not is_admin(reactor):
        if str(payload.emoji) in (APPROVE_EMOJI, REJECT_EMOJI):
            print(f"⚠️ [無視] {reactor} は「{ADMIN_ROLE_NAME}」を持っていません")
        return

    channel = guild.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)

    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    applicant = message.author
    emoji = str(payload.emoji)
    data = parse_application(message.content)

    if emoji == APPROVE_EMOJI and data:
        affiliation = data.get("所属", "")
        name  = data.get("名前", applicant.display_name)
        grade = data.get("学年", "")
        dept  = data.get("学科", "")

        # ロール判定
        if "OMU" in affiliation or "大阪公立" in affiliation:
            role_key = "omu"
        elif "OB" in affiliation or "OG" in affiliation or "卒業" in affiliation:
            role_key = "alumni"
        else:
            role_key = "external"

        role    = get_role(guild, role_key)
        pending = get_role(guild, "pending")

        if role:
            await applicant.add_roles(role)
            print(f"✅ [承認] {applicant.display_name} に「{ROLE_NAMES[role_key]}」を付与")
        else:
            print(f"❌ [失敗] ロール「{ROLE_NAMES[role_key]}」がサーバーに存在しません")
        if pending and pending in applicant.roles:
            await applicant.remove_roles(pending)

        # ニックネーム変更のデバッグ
        nick = format_nickname(name, grade, dept)
        print(f"DEBUG: 取得情報 -> 名前: {name}, 学年: {grade}, 学科: {dept}")
        print(f"DEBUG: 生成されたニックネーム -> {nick}")

        if nick != applicant.display_name:
            try:
                await applicant.edit(nick=nick)
                print(f"✅ [名前変更] {applicant.display_name} -> {nick}")
            except discord.Forbidden:
                print(f"❌ [権限エラー] {applicant.display_name} の名前変更権限がありませんでした（ボットより上の役職か、サーバーオーナーの可能性があります）")
            except Exception as e:
                print(f"❌ [エラー] 名前変更中に予期せぬエラーが発生しました: {e}")
        else:
            print("ℹ️ [情報] 現在のニックネームと同じため、変更をスキップしました")

        await channel.send(
            f"{applicant.mention} 承認しました！ロール「{ROLE_NAMES[role_key]}」を付与しました。",
            delete_after=10,
        )

    elif emoji == APPROVE_EMOJI:
        # ✅ は押されたが「所属：」行が読めなかった。無言だと押した側が成功と誤認する
        print(f"❌ [パース失敗] {applicant.display_name} の申請に「所属」行がありません")
        await channel.send(
            f"{applicant.mention} 「所属：OMU / 外部 / OB・OG」の行が読み取れませんでした。"
            "テンプレートの形式で書き直してください。",
            delete_after=30,
        )

    elif emoji == REJECT_EMOJI:
        await channel.send(
            f"{applicant.mention} 申請を確認できませんでした。再度申請するか、管理者にDMしてください。",
            delete_after=10,
        )


# ─────────────────────────────────────────
# コマンド: 既存メンバー一括ロール付与
# !bulk_assign と入力 + CSVファイル添付
#
# CSVフォーマット（1行目はヘッダー）:
# user_id,role,name,grade,dept
# 123456789,omu,山田太郎,2,情報
# 987654321,external,鈴木花子,,
# ─────────────────────────────────────────
@bot.command(name="bulk_assign")
@commands.has_role(ADMIN_ROLE_NAME)
async def bulk_assign(ctx: commands.Context):
    if not ctx.message.attachments:
        await ctx.send("CSVファイルを添付してください。")
        return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith(".csv"):
        await ctx.send(".csvファイルを添付してください。")
        return

    raw = await attachment.read()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))

    success, failed = 0, 0
    for row in reader:
        try:
            # ユーザーをキャッシュ、もしくはサーバーから再取得
            member = ctx.guild.get_member(int(row["user_id"]))
            if not member:
                try:
                    member = await ctx.guild.fetch_member(int(row["user_id"]))
                except Exception:
                    print(f"⚠️ [bulk_assign] メンバーが見つかりません: {row['user_id']}")
                    failed += 1
                    continue

            role_key = row.get("role", "").strip()
            role    = get_role(ctx.guild, role_key)
            pending = get_role(ctx.guild, "pending")

            if role:
                await member.add_roles(role)
            if pending and pending in member.roles:
                await member.remove_roles(pending)

            # ニックネーム変更（name列がある場合）
            name  = row.get("name", "").strip()
            grade = row.get("grade", "").strip()
            dept  = row.get("dept", "").strip()
            if name:
                try:
                    nick = format_nickname(name, grade, dept)
                    await member.edit(nick=nick)
                except discord.Forbidden:
                    pass

            success += 1
            await asyncio.sleep(0.5)  # レート制限対策

        except Exception as e:
            print(f"[bulk_assign] エラー: {row} → {e}")
            failed += 1

    await ctx.send(f"一括処理完了: 成功 {success} 件 / 失敗 {failed} 件")


# ─────────────────────────────────────────
# コマンド: 手動ロール付与（Carl-bot代替）
# !assign @user omu 山田太郎 2 情報
# ─────────────────────────────────────────
@bot.command(name="assign")
@commands.has_role(ADMIN_ROLE_NAME)
async def assign(ctx: commands.Context, member: discord.Member, role_key: str,
                 name: str = "", grade: str = "", dept: str = ""):
    role    = get_role(ctx.guild, role_key)
    pending = get_role(ctx.guild, "pending")

    if not role:
        await ctx.send(f"ロールキー「{role_key}」が見つかりません。omu / external / alumni を指定してください。")
        return

    await member.add_roles(role)
    if pending and pending in member.roles:
        await member.remove_roles(pending)

    if name:
        try:
            nick = format_nickname(name, grade, dept)
            await member.edit(nick=nick)
        except discord.Forbidden:
            pass

    await ctx.send(f"{member.mention} に「{role.name}」を付与しました。")


# ─────────────────────────────────────────
# コマンド: OB/OG移行
# !graduate @user
# ─────────────────────────────────────────
@bot.command(name="graduate")
@commands.has_role(ADMIN_ROLE_NAME)
async def graduate(ctx: commands.Context, member: discord.Member):
    omu_role    = get_role(ctx.guild, "omu")
    alumni_role = get_role(ctx.guild, "alumni")

    if omu_role and omu_role in member.roles:
        await member.remove_roles(omu_role)
    if alumni_role:
        await member.add_roles(alumni_role)

    await ctx.send(f"{member.mention} をOB/OGに移行しました。")


# ─────────────────────────────────────────
# コマンド: テンプレート投稿
# !setup_info
# ─────────────────────────────────────────
@bot.command(name="setup_info")
@commands.has_role(ADMIN_ROLE_NAME)
async def setup_info(ctx: commands.Context):
    template = (
        "【初回設定】\n"
        "━━━━━━━━━━━━━━\n"
        "名前：（ニックネーム可）\n"
        "所属：OMU / 外部 / OB・OG\n"
        "学年：（OMUのみ。例: B2）\n"
        "学科：（OMUのみ。例: 情報工）\n"
        "興味：ML、AIツール、Kaggle、強化学習、AI全般など\n"
        "━━━━━━━━━━━━━━\n"
    )
    await ctx.send(template)
    await ctx.send("上記のテンプレートをコピーして、このチャンネルで自己紹介してください。管理者が✅をつけるとユーザーネームとロールが自動で付与されます")


if not TOKEN:
    print("❌ DISCORD_TOKEN が設定されていません。.envファイルを確認してください。")
else:
    bot.run(TOKEN)
