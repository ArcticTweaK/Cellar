{
  lib,
  python3Packages,
  qt6,
  passt,
  util-linux,
  sway,
  wayvnc,
  copyDesktopItems,
  makeDesktopItem,
}:

let
  # the version lives in one place: cellar/__init__.py
  version = lib.head (
    lib.concatMap (l: lib.defaultTo [ ] (builtins.match ''__version__ = "(.*)"'' l)) (
      lib.splitString "\n" (builtins.readFile ../cellar/__init__.py)
    )
  );
in
python3Packages.buildPythonApplication {
  pname = "cellar";
  inherit version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../README.md
      ../LICENSE
      ../data
      (lib.fileset.fileFilter (f: !lib.hasSuffix ".pyc" f.name) ../cellar)
    ];
  };

  build-system = [ python3Packages.setuptools ];

  dependencies = with python3Packages; [
    pyside6
    requests
    cryptography
    secretstorage
  ];

  nativeBuildInputs = [
    qt6.wrapQtAppsHook
    copyDesktopItems
  ];

  buildInputs = [
    qt6.qtbase
    qt6.qtwayland
  ];

  # Python app: hand the Qt wrapper arguments to the Python wrapper instead of wrapping twice.
  dontWrapQtApps = true;
  preFixup = ''
    makeWrapperArgs+=("''${qtWrapperArgs[@]}")
  '';

  # pasta (multi-instance network namespaces), unshare (namespaces), sway + wayvnc (background
  # mode's invisible screens) come with the app, so nothing extra is needed system-wide.
  # flatpak, systemctl, busctl and ydotool are used from the system because they talk to
  # system services.
  makeWrapperArgs = [
    "--suffix"
    "PATH"
    ":"
    (lib.makeBinPath [
      passt
      util-linux
      sway
      wayvnc
    ])
  ];

  desktopItems = [
    (makeDesktopItem {
      name = "cellar";
      desktopName = "Cellar";
      genericName = "Roblox account launcher";
      comment = "Run many Roblox accounts at once through Sober";
      exec = "cellar";
      icon = "cellar";
      categories = [
        "Game"
        "Utility"
      ];
      keywords = [
        "roblox"
        "sober"
        "alts"
        "accounts"
        "multi"
        "instance"
        "macro"
      ];
      startupWMClass = "cellar";
    })
  ];

  postInstall = ''
    install -Dm644 data/cellar.svg $out/share/icons/hicolor/scalable/apps/cellar.svg
    install -Dm644 cellar/data/cellar.png $out/share/icons/hicolor/256x256/apps/cellar.png
  '';

  pythonImportsCheck = [ "cellar" ];

  meta = {
    description = "Run many Roblox accounts at once on Linux through Sober";
    license = lib.licenses.gpl3Only;
    platforms = [ "x86_64-linux" ];
    mainProgram = "cellar";
  };
}
