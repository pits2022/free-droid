# free-droid

Nyíltforrású LLM-re épülő saját finomhangolású AI-robot.

## Projekt leírás

Az `LLM` könyvtárban találhatóak a JSON file-ok a modell finomhangolásához.

A `terraform` könyvtárban vannak a terraform fileok a felhőben futó LLM telepítéséhez és a Raspberry PI5 telepítéséhez.

Az `ansible` könyvtárban találhatóak az Ansible playbookok és inventory.
Az `ansible` inventory-ban két node van: `child-001`, `mother-001`


## Könyvtár struktúra

```
├── CONTEXT.md
├── LICENSE
├── LLM
├── README.md
├── ansible
└── terraform
    ├── cloud
    └── pi5
```

