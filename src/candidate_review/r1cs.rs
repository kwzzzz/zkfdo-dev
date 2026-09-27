use std::collections::{BTreeMap, BTreeSet};

use anyhow::{ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};

use super::schema::R1csShape;

pub(crate) type LinearCombination = BTreeMap<u32, BigUint>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct Constraint {
    pub(crate) a: LinearCombination,
    pub(crate) b: LinearCombination,
    pub(crate) c: LinearCombination,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct R1cs {
    pub(crate) prime: BigUint,
    pub(crate) shape: R1csShape,
    pub(crate) constraints: Vec<Constraint>,
    pub(crate) wire_labels: Vec<u64>,
}

impl R1cs {
    pub(crate) fn parse(bytes: &[u8]) -> Result<Self> {
        let mut source = Reader::new(bytes, "R1CS file");
        ensure!(source.take(4)? == b"r1cs", "invalid R1CS magic");
        ensure!(source.u32()? == 1, "unsupported R1CS version");

        let section_count = source.u32()?;
        ensure!(
            section_count == 3,
            "R1CS must contain exactly three sections, found {section_count}"
        );
        let mut sections = BTreeMap::new();
        for _ in 0..section_count {
            let kind = source.u32()?;
            let length = usize::try_from(source.u64()?)
                .context("R1CS section length does not fit in memory")?;
            ensure!(
                sections.insert(kind, source.take(length)?).is_none(),
                "duplicate R1CS section {kind}"
            );
        }
        source.finish()?;
        ensure!(
            sections.keys().copied().eq([1, 2, 3]),
            "R1CS section set must be exactly {{1, 2, 3}}"
        );

        let mut header = Reader::new(sections[&1], "R1CS header section");
        let field_bytes = usize::try_from(header.u32()?)
            .context("R1CS field-byte count does not fit in memory")?;
        ensure!(field_bytes > 0, "R1CS field-byte count must be positive");
        let prime = BigUint::from_bytes_le(header.take(field_bytes)?);
        ensure!(prime > BigUint::one(), "R1CS field modulus must exceed one");
        let shape = R1csShape {
            wires: usize::try_from(header.u32()?)
                .context("R1CS wire count does not fit in memory")?,
            public_outputs: usize::try_from(header.u32()?)
                .context("R1CS public-output count does not fit in memory")?,
            public_inputs: usize::try_from(header.u32()?)
                .context("R1CS public-input count does not fit in memory")?,
            private_inputs: usize::try_from(header.u32()?)
                .context("R1CS private-input count does not fit in memory")?,
            labels: header.u64()?,
            constraints: usize::try_from(header.u32()?)
                .context("R1CS constraint count does not fit in memory")?,
        };
        header.finish()?;
        validate_header_shape(&shape)?;

        let wire_count = shape.wires;
        let constraint_count = shape.constraints;
        let minimum_constraint_bytes = constraint_count
            .checked_mul(3 * std::mem::size_of::<u32>())
            .context("R1CS constraint count overflows its minimum encoded size")?;
        ensure!(
            minimum_constraint_bytes <= sections[&2].len(),
            "R1CS constraint count cannot fit in the constraint section"
        );
        let expected_label_bytes = wire_count
            .checked_mul(std::mem::size_of::<u64>())
            .context("R1CS wire count overflows its label-section size")?;
        ensure!(
            expected_label_bytes == sections[&3].len(),
            "R1CS wire-label section length does not match its wire count"
        );
        let mut constraint_reader = Reader::new(sections[&2], "R1CS constraint section");
        let mut constraints = Vec::with_capacity(constraint_count);
        for constraint_index in 0..constraint_count {
            let a = parse_linear_combination(
                &mut constraint_reader,
                field_bytes,
                &prime,
                wire_count,
                constraint_index,
                "A",
            )?;
            let b = parse_linear_combination(
                &mut constraint_reader,
                field_bytes,
                &prime,
                wire_count,
                constraint_index,
                "B",
            )?;
            let c = parse_linear_combination(
                &mut constraint_reader,
                field_bytes,
                &prime,
                wire_count,
                constraint_index,
                "C",
            )?;
            constraints.push(Constraint { a, b, c });
        }
        constraint_reader.finish()?;

        let mut label_reader = Reader::new(sections[&3], "R1CS wire-label section");
        let mut wire_labels = Vec::with_capacity(wire_count);
        let mut seen_labels = BTreeSet::new();
        for wire in 0..wire_count {
            let label = label_reader.u64()?;
            ensure!(
                label < shape.labels,
                "R1CS wire {wire} has out-of-range label {label} (label count {})",
                shape.labels
            );
            ensure!(
                seen_labels.insert(label),
                "R1CS label {label} represents more than one wire"
            );
            wire_labels.push(label);
        }
        label_reader.finish()?;

        Ok(Self {
            prime,
            shape,
            constraints,
            wire_labels,
        })
    }

    pub(crate) fn validate_shape(&self, expected: &R1csShape) -> Result<()> {
        ensure!(
            &self.shape == expected,
            "R1CS shape mismatch: expected {expected:?}, found {:?}",
            self.shape
        );
        Ok(())
    }

    pub(crate) fn validate_assignment(&self, assignment: &[BigUint]) -> Result<()> {
        let expected_len = self.shape.wires;
        ensure!(
            assignment.len() == expected_len,
            "R1CS assignment length mismatch: expected {expected_len}, found {}",
            assignment.len()
        );
        ensure!(
            assignment.first() == Some(&BigUint::one()),
            "R1CS constant wire 0 must equal canonical field one"
        );
        for (wire, value) in assignment.iter().enumerate() {
            ensure!(
                value < &self.prime,
                "R1CS wire {wire} is not a canonical field element"
            );
        }
        Ok(())
    }

    pub(crate) fn failed_constraint_indices(&self, assignment: &[BigUint]) -> Result<Vec<usize>> {
        self.validate_assignment(assignment)?;
        let mut failed = Vec::new();
        for (index, constraint) in self.constraints.iter().enumerate() {
            let a = evaluate_linear_combination(&constraint.a, assignment, &self.prime);
            let b = evaluate_linear_combination(&constraint.b, assignment, &self.prime);
            let c = evaluate_linear_combination(&constraint.c, assignment, &self.prime);
            if (a * b) % &self.prime != c {
                failed.push(index);
            }
        }
        Ok(failed)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct Symbol {
    pub(crate) wire: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SymbolTable {
    pub(crate) by_name: BTreeMap<String, Symbol>,
    pub(crate) wire_to_names: Vec<Vec<String>>,
    pub(crate) eliminated_names: BTreeSet<String>,
}

impl SymbolTable {
    pub(crate) fn parse(bytes: &[u8], r1cs: &R1cs) -> Result<Self> {
        let text = std::str::from_utf8(bytes).context("SYM is not valid UTF-8")?;
        let wire_count = r1cs.shape.wires;
        let mut by_name = BTreeMap::new();
        let mut wire_to_names = vec![Vec::new(); wire_count];
        let mut eliminated_names = BTreeSet::new();
        let mut label_wires = r1cs
            .wire_labels
            .iter()
            .enumerate()
            .map(|(wire, label)| (*label, wire as i64))
            .collect::<BTreeMap<_, _>>();

        for (line_index, line) in text.lines().enumerate() {
            let line_number = line_index + 1;
            ensure!(!line.is_empty(), "empty SYM line {line_number}");
            let fields: Vec<_> = line.split(',').collect();
            ensure!(
                fields.len() == 4,
                "SYM line {line_number} must have exactly four comma-separated fields"
            );
            let label = parse_unsigned_decimal(fields[0], "label", line_number)?;
            let wire = parse_signed_decimal(fields[1], "wire", line_number)?;
            parse_unsigned_decimal(fields[2], "component", line_number)?;
            let name = fields[3];
            ensure!(!name.is_empty(), "SYM line {line_number} has an empty name");
            ensure!(
                !by_name.contains_key(name),
                "duplicate SYM name {name:?} on line {line_number}"
            );
            ensure!(
                label < r1cs.shape.labels,
                "SYM line {line_number} has out-of-range label {label}"
            );

            if wire >= 0 {
                let wire_index = usize::try_from(wire)
                    .with_context(|| format!("SYM line {line_number} has invalid wire {wire}"))?;
                ensure!(
                    wire_index < wire_count,
                    "SYM line {line_number} has out-of-range wire {wire}"
                );
                wire_to_names[wire_index].push(name.to_owned());
            } else {
                eliminated_names.insert(name.to_owned());
            }

            // R1CS records one representative label per wire. Other labels may
            // alias that wire, but a label cannot describe conflicting wires.
            if let Some(previous_wire) = label_wires.insert(label, wire) {
                ensure!(
                    previous_wire == wire,
                    "SYM line {line_number} label {label} has conflicting wire mappings"
                );
            }

            by_name.insert(name.to_owned(), Symbol { wire });
        }

        for names in &mut wire_to_names {
            names.sort();
        }
        Ok(Self {
            by_name,
            wire_to_names,
            eliminated_names,
        })
    }
}

fn validate_header_shape(shape: &R1csShape) -> Result<()> {
    ensure!(shape.wires > 0, "R1CS must contain constant wire 0");
    let wire_count = u64::try_from(shape.wires).context("R1CS wire count exceeds u64")?;
    ensure!(
        shape.labels >= wire_count,
        "R1CS label count must be at least its wire count"
    );
    let declared_io = u64::try_from(shape.public_outputs)
        .context("R1CS public-output count exceeds u64")?
        + u64::try_from(shape.public_inputs).context("R1CS public-input count exceeds u64")?
        + u64::try_from(shape.private_inputs).context("R1CS private-input count exceeds u64")?
        + 1;
    ensure!(
        declared_io <= wire_count,
        "R1CS declared inputs and outputs exceed its wire count"
    );
    Ok(())
}

fn parse_linear_combination(
    reader: &mut Reader<'_>,
    field_bytes: usize,
    prime: &BigUint,
    wire_count: usize,
    constraint_index: usize,
    side: &str,
) -> Result<LinearCombination> {
    let term_count = usize::try_from(reader.u32()?)
        .context("R1CS linear-combination term count does not fit in memory")?;
    let mut terms = BTreeMap::new();
    for term_index in 0..term_count {
        let wire = reader.u32()?;
        let wire_index = usize::try_from(wire).context("R1CS wire index does not fit in memory")?;
        ensure!(
            wire_index < wire_count,
            "constraint {constraint_index} {side} term {term_index} has out-of-range wire {wire}"
        );
        let coefficient = BigUint::from_bytes_le(reader.take(field_bytes)?);
        ensure!(
            !coefficient.is_zero() && &coefficient < prime,
            "constraint {constraint_index} {side} term {term_index} has a zero or noncanonical coefficient"
        );
        ensure!(
            terms.insert(wire, coefficient).is_none(),
            "constraint {constraint_index} {side} repeats wire {wire}"
        );
    }
    Ok(terms)
}

fn evaluate_linear_combination(
    terms: &LinearCombination,
    assignment: &[BigUint],
    prime: &BigUint,
) -> BigUint {
    terms
        .iter()
        .fold(BigUint::zero(), |accumulator, (wire, coefficient)| {
            let term = (coefficient * &assignment[*wire as usize]) % prime;
            (accumulator + term) % prime
        })
}

fn parse_unsigned_decimal(text: &str, field: &str, line: usize) -> Result<u64> {
    ensure!(
        !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit()),
        "SYM line {line} has a non-decimal {field}"
    );
    text.parse()
        .with_context(|| format!("SYM line {line} {field} is out of range"))
}

fn parse_signed_decimal(text: &str, field: &str, line: usize) -> Result<i64> {
    let digits = text.strip_prefix('-').unwrap_or(text);
    ensure!(
        !digits.is_empty() && digits.bytes().all(|byte| byte.is_ascii_digit()),
        "SYM line {line} has a non-decimal {field}"
    );
    let value: i64 = text
        .parse()
        .with_context(|| format!("SYM line {line} {field} is out of range"))?;
    ensure!(
        !text.starts_with('-') || value < 0,
        "SYM line {line} has a noncanonical {field}"
    );
    Ok(value)
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
    context: &'static str,
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8], context: &'static str) -> Self {
        Self {
            bytes,
            offset: 0,
            context,
        }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8]> {
        let end = self
            .offset
            .checked_add(length)
            .with_context(|| format!("{} offset overflow", self.context))?;
        ensure!(end <= self.bytes.len(), "truncated {}", self.context);
        let result = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(result)
    }

    fn u32(&mut self) -> Result<u32> {
        let bytes: [u8; 4] = self
            .take(4)?
            .try_into()
            .expect("a four-byte slice was requested");
        Ok(u32::from_le_bytes(bytes))
    }

    fn u64(&mut self) -> Result<u64> {
        let bytes: [u8; 8] = self
            .take(8)?
            .try_into()
            .expect("an eight-byte slice was requested");
        Ok(u64::from_le_bytes(bytes))
    }

    fn finish(&self) -> Result<()> {
        ensure!(
            self.offset == self.bytes.len(),
            "unexpected trailing bytes in {}",
            self.context
        );
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PRIME: u64 = 257;

    #[test]
    fn parses_and_evaluates_a_strict_r1cs() {
        let bytes = fixture_r1cs(None);
        let r1cs = R1cs::parse(&bytes).unwrap();
        assert_eq!(r1cs.prime, BigUint::from(PRIME));
        assert_eq!(r1cs.shape, fixture_shape());
        assert_eq!(r1cs.wire_labels, vec![0, 1, 2]);
        r1cs.validate_shape(&fixture_shape()).unwrap();

        let satisfying = biguints(&[1, 7, 7]);
        assert_eq!(
            r1cs.failed_constraint_indices(&satisfying).unwrap(),
            Vec::<usize>::new()
        );
        let failing = biguints(&[1, 7, 8]);
        assert_eq!(r1cs.failed_constraint_indices(&failing).unwrap(), vec![0]);
    }

    #[test]
    fn rejects_noncanonical_assignments_and_wrong_shapes() {
        let r1cs = R1cs::parse(&fixture_r1cs(None)).unwrap();
        assert!(r1cs.failed_constraint_indices(&biguints(&[1, 2])).is_err());
        assert!(r1cs
            .failed_constraint_indices(&biguints(&[0, 2, 2]))
            .is_err());
        assert!(r1cs
            .failed_constraint_indices(&biguints(&[1, PRIME, 0]))
            .is_err());

        let mut wrong = fixture_shape();
        wrong.constraints += 1;
        assert!(r1cs.validate_shape(&wrong).is_err());
    }

    #[test]
    fn rejects_invalid_container_and_header_encodings() {
        let mut bad_magic = fixture_r1cs(None);
        bad_magic[0] = b'R';
        assert!(R1cs::parse(&bad_magic).is_err());

        let mut trailing = fixture_r1cs(None);
        trailing.push(0);
        assert!(R1cs::parse(&trailing).is_err());

        let duplicate_sections = assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(None)),
            (2, label_section()),
        ]);
        assert!(R1cs::parse(&duplicate_sections).is_err());

        let unexpected_sections = assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(None)),
            (4, label_section()),
        ]);
        assert!(R1cs::parse(&unexpected_sections).is_err());
    }

    #[test]
    fn rejects_bad_linear_combination_terms() {
        for fault in [
            TermFault::ZeroCoefficient,
            TermFault::NoncanonicalCoefficient,
            TermFault::DuplicateWire,
            TermFault::OutOfRangeWire,
        ] {
            assert!(R1cs::parse(&fixture_r1cs(Some(fault))).is_err());
        }
    }

    #[test]
    fn rejects_bad_label_section() {
        let truncated = assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(None)),
            (3, vec![0; 16]),
        ]);
        assert!(R1cs::parse(&truncated).is_err());

        let mut labels = label_section();
        labels[16..24].copy_from_slice(&3_u64.to_le_bytes());
        let out_of_range = assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(None)),
            (3, labels),
        ]);
        assert!(R1cs::parse(&out_of_range).is_err());

        let mut labels = label_section();
        labels[16..24].copy_from_slice(&1_u64.to_le_bytes());
        let duplicate = assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(None)),
            (3, labels),
        ]);
        assert!(R1cs::parse(&duplicate).is_err());
    }

    #[test]
    fn parses_aliases_and_eliminated_symbols_separately() {
        let mut r1cs = R1cs::parse(&fixture_r1cs(None)).unwrap();
        r1cs.shape.labels = 4;
        let sym = b"1,1,0,main.in\n1,1,1,main.alias\n2,2,0,main.out\n3,-1,1,main.eliminated\n";
        let table = SymbolTable::parse(sym, &r1cs).unwrap();
        assert_eq!(
            table.wire_to_names[1],
            vec!["main.alias".to_owned(), "main.in".to_owned()]
        );
        assert_eq!(table.by_name["main.out"].wire, 2);
        assert_eq!(
            table.eliminated_names,
            BTreeSet::from(["main.eliminated".to_owned()])
        );
    }

    #[test]
    fn parses_distinct_label_positive_wire_aliases() {
        let mut r1cs = R1cs::parse(&fixture_r1cs(None)).unwrap();
        r1cs.shape.labels = 5;
        let sym = b"3,1,1,main.alias\n1,1,0,main.in\n2,2,0,main.out\n4,-1,1,main.eliminated\n";
        let table = SymbolTable::parse(sym, &r1cs).unwrap();
        assert_eq!(table.by_name["main.alias"].wire, 1);
        assert_eq!(
            table.wire_to_names[1],
            vec!["main.alias".to_owned(), "main.in".to_owned()]
        );
        assert!(table.eliminated_names.contains("main.eliminated"));
    }

    #[test]
    fn rejects_conflicting_alias_label_mappings() {
        let mut r1cs = R1cs::parse(&fixture_r1cs(None)).unwrap();
        r1cs.shape.labels = 4;
        for sym in [
            "3,1,0,main.alias\n3,2,0,main.other\n",
            "3,1,0,main.alias\n3,-1,0,main.eliminated\n",
            "1,-1,0,main.eliminated\n",
        ] {
            assert!(SymbolTable::parse(sym.as_bytes(), &r1cs).is_err());
        }
    }

    #[test]
    fn rejects_malformed_or_conflicting_symbols() {
        let r1cs = R1cs::parse(&fixture_r1cs(None)).unwrap();
        for sym in [
            "1,1,0\n",
            "1,1,0,main.in\n1,2,0,main.in\n",
            "2,1,0,main.in\n",
            "1,3,0,main.in\n",
            "3,-1,0,main.eliminated\n",
            "1,+1,0,main.in\n",
            "1,1,0,main,in\n",
            "1,1,0,main.in\n\n2,2,0,main.out\n",
        ] {
            assert!(
                SymbolTable::parse(sym.as_bytes(), &r1cs).is_err(),
                "accepted {sym:?}"
            );
        }
    }

    fn preserved_artifact(relative: &str) -> Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(relative);
        std::fs::read(&path).unwrap_or_else(|error| panic!("read {}: {error}", path.display()))
    }

    #[test]
    #[ignore = "requires gitignored compiled v1.1/v2 evidence; run cargo test --lib -- --ignored"]
    fn parses_preserved_v1_and_v2_artifacts() {
        let v1_r1cs = R1cs::parse(&preserved_artifact(
            "reports/controlled-v1.1-execution-2026-09-20/evidence/\
             vulnerable-component/compiled/circuit.r1cs",
        ))
        .unwrap();
        v1_r1cs
            .validate_shape(&R1csShape {
                wires: 5,
                labels: 5,
                public_outputs: 1,
                public_inputs: 0,
                private_inputs: 2,
                constraints: 1,
            })
            .unwrap();
        let v1_symbols = SymbolTable::parse(
            &preserved_artifact(
                "reports/controlled-v1.1-execution-2026-09-20/evidence/\
                 vulnerable-component/compiled/circuit.sym",
            ),
            &v1_r1cs,
        )
        .unwrap();
        assert_eq!(v1_symbols.by_name.len(), 4);
        assert!(v1_symbols.eliminated_names.is_empty());

        let v2_r1cs = R1cs::parse(&preserved_artifact(
            "reports/controlled-v2-execution-2026-09-20/evidence/\
             banyan-vulnerable-compiled/circuit.r1cs",
        ))
        .unwrap();
        v2_r1cs
            .validate_shape(&R1csShape {
                wires: 29,
                labels: 40,
                public_outputs: 2,
                public_inputs: 0,
                private_inputs: 2,
                constraints: 29,
            })
            .unwrap();
        let v2_symbols = SymbolTable::parse(
            &preserved_artifact(
                "reports/controlled-v2-execution-2026-09-20/evidence/\
                 banyan-vulnerable-compiled/circuit.sym",
            ),
            &v2_r1cs,
        )
        .unwrap();
        assert_eq!(v2_symbols.by_name.len(), 39);
        assert_eq!(v2_symbols.eliminated_names.len(), 11);
        assert!(v2_symbols.wire_to_names[1..]
            .iter()
            .all(|names| names.len() == 1));
    }

    #[derive(Clone, Copy)]
    enum TermFault {
        ZeroCoefficient,
        NoncanonicalCoefficient,
        DuplicateWire,
        OutOfRangeWire,
    }

    fn fixture_shape() -> R1csShape {
        R1csShape {
            wires: 3,
            public_outputs: 1,
            public_inputs: 0,
            private_inputs: 1,
            labels: 3,
            constraints: 1,
        }
    }

    fn fixture_r1cs(fault: Option<TermFault>) -> Vec<u8> {
        assemble_r1cs(vec![
            (1, header_section()),
            (2, constraint_section(fault)),
            (3, label_section()),
        ])
    }

    fn assemble_r1cs(sections: Vec<(u32, Vec<u8>)>) -> Vec<u8> {
        let mut result = b"r1cs".to_vec();
        push_u32(&mut result, 1);
        push_u32(&mut result, sections.len() as u32);
        for (kind, section) in sections {
            push_u32(&mut result, kind);
            push_u64(&mut result, section.len() as u64);
            result.extend(section);
        }
        result
    }

    fn header_section() -> Vec<u8> {
        let mut header = Vec::new();
        push_u32(&mut header, 2);
        header.extend(PRIME.to_le_bytes()[..2].iter().copied());
        let shape = fixture_shape();
        push_u32(&mut header, shape.wires.try_into().unwrap());
        push_u32(&mut header, shape.public_outputs.try_into().unwrap());
        push_u32(&mut header, shape.public_inputs.try_into().unwrap());
        push_u32(&mut header, shape.private_inputs.try_into().unwrap());
        push_u64(&mut header, shape.labels);
        push_u32(&mut header, shape.constraints.try_into().unwrap());
        header
    }

    fn constraint_section(fault: Option<TermFault>) -> Vec<u8> {
        let mut section = Vec::new();
        match fault {
            Some(TermFault::DuplicateWire) => {
                push_u32(&mut section, 2);
                push_term(&mut section, 1, 1);
                push_term(&mut section, 1, 1);
            }
            Some(TermFault::OutOfRangeWire) => {
                push_u32(&mut section, 1);
                push_term(&mut section, 3, 1);
            }
            Some(TermFault::ZeroCoefficient) => {
                push_u32(&mut section, 1);
                push_term(&mut section, 1, 0);
            }
            Some(TermFault::NoncanonicalCoefficient) => {
                push_u32(&mut section, 1);
                push_term(&mut section, 1, PRIME);
            }
            None => {
                push_u32(&mut section, 1);
                push_term(&mut section, 1, 1);
            }
        }
        push_u32(&mut section, 1);
        push_term(&mut section, 0, 1);
        push_u32(&mut section, 1);
        push_term(&mut section, 2, 1);
        section
    }

    fn label_section() -> Vec<u8> {
        let mut labels = Vec::new();
        for label in 0..3 {
            push_u64(&mut labels, label);
        }
        labels
    }

    fn push_term(destination: &mut Vec<u8>, wire: u32, coefficient: u64) {
        push_u32(destination, wire);
        destination.extend(coefficient.to_le_bytes()[..2].iter().copied());
    }

    fn push_u32(destination: &mut Vec<u8>, value: u32) {
        destination.extend(value.to_le_bytes());
    }

    fn push_u64(destination: &mut Vec<u8>, value: u64) {
        destination.extend(value.to_le_bytes());
    }

    fn biguints(values: &[u64]) -> Vec<BigUint> {
        values.iter().copied().map(BigUint::from).collect()
    }
}
