# 21 - Two-pass mesh: GPU hang jest systematyczny, nie zalezny od danych

Data: 2026-11-28. XCL branch `fix/sparse-read-fault` (b548c8e3 + commity diagnostyczne).
ECC: agent-introspection-debugging (izolacja po jednej zmiennej), terminal-ops (dowody z logow).
REA: nie dotyczy (logi wlasnego runtime'u; cel REA nadal bez providera Ghidra).

## 1. Co juz wiadomo (dowody z przebiegow 240-360 s)
- `XCL_SKIP_TWO_PASS=mesh` (compute dziala, mesh pominiety): brak TDR, 300 s.
- `XCL_SKIP_TWO_PASS=compute` (mesh z pustymi rekordami): **TDR ~216 s** -> dane rekordow
  nie maja znaczenia.
- `XCL_TWO_PASS_NO_PS=1` (mesh bez PS tytulu): **TDR ~216 s** -> PS nie jest sprawca.
- `XCL_MESH_LIMIT=1` (jeden dispatch mesh w calym procesie): **TDR ~216 s** -> jeden dispatch
  wystarcza; to nie narastanie i nie konkretny pipeline.
- `XCL_SKIP_DM_MESH=1` (tylko EI) -> TDR ~210 s; `XCL_SKIP_EI_MESH=1` (tylko DM) -> TDR ~248 s.
  Obie sciezki wisza.
- `XCL_SKIP_MS` na czterech najczestszych hashach z konca (175c6b4b, fd1597e2, ebe6d99a,
  c7823d30) -> TDR nadal.
- Sample count mesh PSO = 1 (nie MSAA). Stany widziane: 3 RT + console DSV 20 (scena glowna),
  0 RT + DSV 20 (depth-only), 5 RT (29/28/28/28/28), 1 RT (49 / 41 + DSV 55).
- DRED: `page fault at GPU VA 0x0; allocations there: []` i brak breadcrumbow (sterownik
  nie zapisuje historii operacji). VA 0 moze byc prawdziwym odczytem null-descriptora.
- Czas TDR jest powtarzalny (~216 s) takze przy roznych skipach -> albo staly event gry,
  albo odroczony skutek pierwszego dispatchu mesh.

## 2. Co to wyklucza
- Zly uklad rekordow / zle dane z compute (puste rekordy tez wisza).
- Konkretny PS albo konkretny MS (bez PS i bez 4 najczestszych tez wisi).
- MSAA / sample mismatch.
- Narastanie po tysiacach passow (jeden wystarcza).

## 3. Co zostaje
1. Null/invalid deskryptor w wiazaniu two-pass (DRED VA 0) - sprawdzic, czy kazdy root UAV
   (u0..u5) ma niezerowy VA i czy ABI RS mapuje je na rejestry, ktorych uzywa shader.
2. Niezgodnosc stanu PSO z RTV/DSV przy draw (format/typeless) - warstwa debug D3D12
   (`XCL_D3D12_DEBUG=1`) powinna to nazwac.
3. Blad sterownika przy DispatchMesh z ABI XCL (root signature / descriptor heaps).
4. Minimalny repro w tescie: PSO + ABI RS + bufor rekordow + jeden DispatchMesh + readback,
   zamiast 5-minutowych przebiegow gry.

## 4. Nastepny krok
- Przebieg z `XCL_D3D12_DEBUG=1` (w toku): komunikaty walidacji przy pierwszym mesh draw.
- Jesli walidacja milczy: repro w tescie (sekundy na iteracje).

## 5. Warstwa debug D3D12 niedostepna; nowe dowody z przebiegu 360 s
- `XCL_D3D12_DEBUG=1`: "debug layer requested but unavailable: 0x887A002D" (brak zgodnego
  D3D12SDKLayers.dll dla Agility SDK) - walidacji nie ma, trzeba by dolaczyc warstwe
  z Windows SDK w wersji zgodnej z D3D12Core.dll.
- Przebieg: TDR ~216 s, potem sterownik odrzuca compute PSO z 0x887a0005 (232 s), a `submit`
  (ExecuteCommandLists) wisi 31-39 s ("hold: 2 PC call(s) ... oldest: submit"). Proces konczy
  sie 0xC0000005 w kodzie tytulu. Czyli dlugi submit to skutek zawieszonego GPU, nie przyczyna.
- Osobny, realny problem: 8 ostrzezen "a command list is submitted while its previous submit is
  still on the GPU (debug layer id 553)" w fazie 2D (46-94 s). XCL ma mechanizm list zastepczych
  (`alloc_pool.rs`, `list_x.rs`), ale obejscie sie wyczerpalo. Ponowny submit listy bedacej na GPU
  jest nielegalny i moze zawieszac GPU - kandydat do zbadania niezaleznie od mesh.

## 6. Ocena
- Jeden DispatchMesh wystarcza, zeby pozniej zawiesic GPU; bez danych, bez PS, bez MSAA.
- To nie jest blad pojedynczego shadera ani przeliczania rekordow: to stan/wiazanie two-pass
  albo sterownik. Ich wlasny XCL wylaczyl two-pass domyslnie ("can reset the GPU") - ten sam mur.
- Najkrotsza droga do odpowiedzi: minimalny repro w tescie (PSO + ABI RS + bufor rekordow +
  jeden DispatchMesh + readback), iteracje w sekundach zamiast 5-minutowych przebiegow gry.
