{
  description = "Cellar - run many Roblox accounts at once on Linux through Sober";

  # NixOS: try it with `nix run github:ArcticTweaK/Cellar`, or add it to your config:
  #   inputs.cellar.url = "github:ArcticTweaK/Cellar";
  #   inputs.cellar.inputs.nixpkgs.follows = "nixpkgs";
  #   environment.systemPackages = [ inputs.cellar.packages.x86_64-linux.default ];
  # It brings its own pasta, unshare, sway and wayvnc. Sober comes from Flathub:
  #   services.flatpak.enable = true;  then  flatpak install flathub org.vinegarhq.Sober
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system} = {
        cellar = pkgs.callPackage ./nix/package.nix { };
        default = self.packages.${system}.cellar;
      };

      apps.${system}.default = {
        type = "app";
        program = "${self.packages.${system}.default}/bin/cellar";
      };

      overlays.default = final: _prev: {
        cellar = final.callPackage ./nix/package.nix { };
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (pkgs.python3.withPackages (
            p: with p; [
              pyside6
              requests
              cryptography
              secretstorage
            ]
          ))
          pkgs.passt
          pkgs.sway
          pkgs.wayvnc
          pkgs.ruff
        ];
        shellHook = ''echo "Run Cellar from source:  python -m cellar"'';
      };
    };
}
