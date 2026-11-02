# call_graph の構成 (v0.8.3)

## 目的

シンボル (関数・変数・型) を依存順のレベルに並べ、呼び出される側から
呼び出す側へ LLM 解析を進められるようにする。同じ再帰グループ (SCC) は
同じレベルで扱う。

## モジュール構成

各ファイルは 6KiB 以下。`pystdoc.call_graph` は従来の import 先として
全ての公開名を再公開するので、既存コードの変更は不要。

| モジュール | 内容 |
|---|---|
| `call_graph.py` | `order_symbols_by_levels`, `order_symbols_bottom_up` と再公開 |
| `call_graph_nodes.py` | `SymbolNode`, `flatten_symbols` |
| `var_linker.py` | `link_variables_to_functions` |
| `scc.py` | `tarjan_scc` |
| `level_graph.py` | レベル付けの補助関数 |
| `callee_summary.py` | `build_callee_context_summary` |

`order_symbols_by_levels` が `tarjan_scc` を `call_graph` の名前空間から
呼ぶ点は意図的である。テストが `pystdoc.call_graph.tarjan_scc` を
差し替えるため、この関数は `call_graph.py` に置いている。

## 処理の流れ (order_symbols_by_levels)

1. `index_nodes`: unique_id / FQDN / 短い名前の索引を作る。
2. `build_callee_edges`: 呼び出し先の名前をノード ID に解決する。
3. `tarjan_scc`: 関数だけで SCC を求める。
4. `assign_scc_groups`: 相互再帰の相手を `scc_group_ids` に入れる。
5. `build_condensation`: SCC を縮約した DAG を作る。
6. `rank_sccs`: 葉から順にランクを付ける。
7. `assemble_levels`: 非関数をレベル 0 に置き、関数をランク順に並べる。

## 変数と関数の紐付け (link_variables_to_functions)

変数・定数・型ごとに、参照している関数を探す。判定は次の2つの和集合。

- 宣言行が関数の行範囲に含まれる (同一ファイル)。
- 関数本体に名前が単語として現れる (`\bname\b` と等価)。

実装は次のとおり。

1. 各ファイルを1回だけ読む。
2. 関数本体を `\w+` で単語に分け、「単語 → 関数」の逆引き表を作る。
3. 変数名で逆引き表を引く。
4. 名前が `\w+` だけで構成されない場合 (例: `~Foo`) のみ、従来どおり
   正規表現で検索する。

読めないファイルは標準エラー出力に警告を出し、そのファイルの関数は
本体の一致判定から外す。行範囲による判定は引き続き有効である。
