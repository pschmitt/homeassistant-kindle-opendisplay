{
  description = "Development environment for Kindle OpenDisplay and Kindle Inkwell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    {
      devShells = nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ] (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.black
              pkgs.cargo
              pkgs.clippy
              pkgs.nixfmt
              pkgs.python314
              pkgs.ruff
              pkgs.rustc
              pkgs.rustfmt
              pkgs.shellcheck
              pkgs.uv
            ];
          };
        }
      );
    };
}
