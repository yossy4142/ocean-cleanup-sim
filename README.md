```markdown
# 海洋プラスチック回収シミュレーション

マルチエージェントシステムを用いた海洋プラスチック回収シミュレーションです。FastAPIによるバックエンドで物理演算と状態管理を行い、WebSocket経由でフロントエンド（HTML5 Canvas）へリアルタイム同期を行います。

## 技術スタック

| コンポーネント | 技術・ライブラリ |
| :--- | :--- |
| **バックエンド** | Python 3.x, FastAPI, Uvicorn, Pydantic, NumPy |
| **フロントエンド** | HTML5, Vanilla JavaScript, Canvas API, QRious |
| **通信** | WebSocket (状態同期), REST API (設定反映) |
| **永続化** | JSON (`leaderboard.json`) |

## システム仕様・アルゴリズム

### 1. エージェント制御（Boidsモデルベース）
魚（Fish）およびロボット（Scout / Collector）の自律移動は、Boidsモデルに独自の引力・斥力を加えた人工ポテンシャル法に基づき計算されます。
* **魚の挙動**: 分離（Separation）、整列（Alignment）、結合（Cohesion）に加え、ロボットからの斥力（回避行動）を計算し、回避時にストレス値が蓄積します。
* **ロボットの挙動**: プレイヤーまたはAIによって設定された重みパラメータ（`w_trash`, `w_avoidfish`, `w_avoidrobot`）の合成ベクトルによって進行方向を決定します。

### 2. 学習AIアルゴリズム（回帰分析）
「VS 学習AIモード」において、CPUの機体編成およびAI重みパラメータは、過去のプレイヤーデータから動的に算出されます。
1. `leaderboard.json` に記録されたソロプレイデータから、スコア上位50%のレコードを抽出。
2. 抽出したレコードの最終スコアを「重み（Weight）」として適用。
3. 各パラメータ（探索機数、回収機数、各種AI重み）の**加重平均**を算出し、小数点以下を丸めてCPUのパラメータとして採用します。

### 3. スコアリングモデル
シミュレーション終了時の最終スコアは以下の式で算出されます。
`Score = (回収数 × 30) - (衝突回数 × 10) - (総消費電力 × 0.2) - (魚の累積ストレス × 0.5)`

---

## 開発・実行環境の構築

依存関係の競合を防ぐため、Pythonの仮想環境（`venv`）を使用した起動を推奨します。

### 前提条件
* Python 3.8 以上
* Git

### セットアップ手順

**1. リポジトリのクローン**
```bash
git clone [https://github.com/yossy4142/ocean-cleanup-sim.git](https://github.com/yossy4142/ocean-cleanup-sim.git)
cd ocean-cleanup-sim
```

**2. 仮想環境の作成と有効化**
```bash
# macOS / Linux の場合
python3 -m venv venv
source venv/bin/activate

# Windows の場合
python -m venv venv
venv\Scripts\activate
```

**3. 依存ライブラリのインストール**
```bash
pip install -r requirements.txt
```

**4. サーバーの起動**
```bash
python -m uvicorn main:app --reload
```

サーバー起動後、ブラウザで `http://localhost:8000` にアクセスしてください。

## ファイル構成

* `main.py`: バックエンドのエントリポイント。APIルーティング、WebSocketハンドラ、メインシミュレーションループ(`simulation_loop`)を内包。
* `index.html`: フロントエンド。SPA（Single Page Application）構成での画面遷移、Canvas描画ロジック、UI操作イベントを管理。
* `leaderboard.json`: 歴代のスコアとパラメータ設定を保持するデータファイル。メタ学習AIのデータソースとして機能。
* `requirements.txt`: Pythonの依存パッケージリスト。
```
