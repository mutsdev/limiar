"""Captura, detecção e rastreamento.

Só esta camada conhece OpenCV e ultralytics. Ela depende de `contagem` e
`dominio`, nunca o contrário — por isso o núcleo da contagem continua
testável sem instalar 2,5 GB de PyTorch.
"""
