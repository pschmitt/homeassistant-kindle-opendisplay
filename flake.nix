{
  description = "Development environment for Kindle OpenDisplay and Kindle Inkwell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  inputs.crane.url = "github:ipetkov/crane";

  outputs =
    { crane, nixpkgs, ... }:
    let
      eachSystem = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      checks = eachSystem (
        system:
        let
          craneLib = crane.mkLib nixpkgs.legacyPackages.${system};
          src = craneLib.cleanCargoSource ./.;
          cargoArtifacts = craneLib.buildDepsOnly { inherit src; };
        in
        {
          protocol = craneLib.cargoTest { inherit src cargoArtifacts; };
        }
      );

      devShells = eachSystem (
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
