# Semantic Target Discovery MVP

`zkfDO targets` turns a supported subset of a full Circom project into concrete template-instantiation candidates. It is intentionally separate from the file scanner: a `.circom` library is source material, not automatically a runnable target.

## Command

```sh
zkfDO targets \
  --project path/to/project \
  --circom-bin circom \
  --output .zkfdo/targets
```

The command searches for a unique top-level `component main`, follows includes reachable from its source file, evaluates concrete arguments, walks nested component instantiations, and writes:

```text
.zkfdo/targets/<discovery-id>/
  discovery.json
  wrappers/
    0000-TargetName/
      target.circom
      circom.stdout.log
      circom.stderr.log
      circom-output/
```

Use `--no-validate` when only wrapper generation is wanted. In that mode wrapper status is `generated`; otherwise it becomes `compile_succeeded`, `compile_failed`, or `compiler_unavailable`.

## Supported Subset

- one top-level `component main = Template(concrete_arguments)` declaration
- templates in the entrypoint file and project-local recursively included files
- scalar template parameters
- scalar component declarations with direct assignment, such as `component hash = Hash(64)`
- separately declared scalar components followed by assignment
- nested component relationships
- integer literals, bound template parameters, parentheses, unary `+`/`-`, and checked integer arithmetic/bitwise operations in template arguments
- preceding scalar compile-time variables such as `var limb = 64`
- optional `parallel` before a direct template call

Every discovered instance records its defining source, concrete parameter vector, parent template and parameters, component name, source line, wrapper path, and validation status. Different concrete parameter vectors remain distinct targets.

## Explicitly Unsupported

- zero or multiple project entrypoints
- component arrays and indexed component assignments
- component instantiation inside `if`, `for`, or `while`
- anonymous/chained component calls such as `Hash(64)(input)`
- parameter expressions involving function calls, arrays, field values, or unknown variables
- ambiguous duplicate template names
- unresolved includes or dependencies outside the scanner's project view
- recursive concrete template instantiation
- wrappers whose included source closure already declares `component main`
- template modifiers or other grammar outside the supported subset

These cases appear in `unsupported` or as a per-target `failure_reason`; they are not silently converted into approximate targets.

## Wrapper Form

```circom
pragma circom 2.1.6;

include "/absolute/path/to/library.circom";

component main = Num2Bits(32);
```

Wrappers are generated outside the source project and never modify original Circom files. Compile success establishes that Circom accepts the isolated wrapper. This MVP does not yet execute zkFuzz against wrappers, so zkFuzz runtime compatibility remains a later integration check.
