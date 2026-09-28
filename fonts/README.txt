PDF 한글 표시용 폰트 (Noto Sans KR, SIL Open Font License - OFL.txt 참고)
- NotoSansKR-Regular.ttf : 보통 굵기 (wght 400)
- NotoSansKR-Bold.ttf    : 굵게 (wght 700)

Google Fonts 는 가변(variable) 폰트만 제공하고 reportlab 은 가변 폰트의 굵기를 고르지 못하므로,
원본 NotoSansKR[wght].ttf 에서 fontTools 로 굵기별 고정 폰트를 뽑아 넣었습니다.
  python -m fontTools.varLib.instancer "NotoSansKR[wght].ttf" wght=400 --static --update-name-table -o NotoSansKR-Regular.ttf
원본: https://github.com/google/fonts/tree/main/ofl/notosanskr
