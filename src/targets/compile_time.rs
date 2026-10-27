//! Conservative source-only compile-time values for the inspection fallback.
//!
//! The fallback is enabled only for explicit bn128 inspection. Integer division
//! and remainder normalize operands to that field; other arithmetic stays in the
//! bounded exact integer subset and never approximates field division. Conditional
//! expressions require both branches to evaluate successfully to scalar integers;
//! even errors in the unselected branch are conservatively refused.

use std::{borrow::Cow, collections::HashMap};

use num_bigint::BigInt;
use num_traits::{ToPrimitive, Zero};

use super::{token_is_symbol, Token, TokenKind};

const MAX_DEPTH: usize = 64;
const MAX_STEPS: usize = 100_000;
const MAX_ARRAY_ELEMENTS: usize = 100_000;

type EvalResult<T> = std::result::Result<T, String>;
pub(super) type Env = HashMap<String, Value>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum Value {
    Int(BigInt),
    Array(Vec<Value>),
    Unknown,
}

impl Value {
    pub(super) fn scalar(&self) -> EvalResult<i128> {
        match self {
            Self::Int(value) => value
                .to_i128()
                .ok_or_else(|| "compile-time integer exceeds the exact i128 subset".into()),
            Self::Array(_) => Err("compile-time scalar expected, found an array".into()),
            Self::Unknown => Err("uninitialized compile-time value".into()),
        }
    }

    pub(super) fn literal(&self) -> String {
        match self {
            Self::Int(value) => value.to_string(),
            Self::Unknown => "__uninitialized_compile_time_value".into(),
            Self::Array(values) => format!(
                "[{}]",
                values
                    .iter()
                    .map(Self::literal)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }

    pub(super) fn validate_initialized(&self) -> EvalResult<()> {
        self.dimensions()?;
        fn initialized(value: &Value) -> bool {
            match value {
                Value::Unknown => false,
                Value::Int(_) => true,
                Value::Array(values) => values.iter().all(initialized),
            }
        }
        if !initialized(self) {
            return Err("uninitialized compile-time value".into());
        }
        Ok(())
    }

    pub(super) fn uninitialized(dims: &[usize]) -> EvalResult<Self> {
        if dims.len() >= MAX_DEPTH || dims.contains(&0) {
            return Err("unsupported empty or deeply nested compile-time array".into());
        }
        let mut size = 1usize;
        let mut cells = 1usize;
        for dim in dims {
            size = size
                .checked_mul(*dim)
                .ok_or_else(|| "compile-time array size overflow".to_owned())?;
            cells = cells
                .checked_add(size)
                .ok_or_else(|| "compile-time array size overflow".to_owned())?;
            if cells > MAX_ARRAY_ELEMENTS {
                return Err("compile-time array exceeds the inspection element limit".into());
            }
        }
        fn build(dims: &[usize]) -> Value {
            match dims.split_first() {
                None => Value::Unknown,
                Some((length, rest)) => Value::Array(vec![build(rest); *length]),
            }
        }
        Ok(build(dims))
    }

    pub(super) fn set_index(&mut self, indices: &[usize], value: Value) -> EvalResult<()> {
        value.validate_initialized()?;
        let mut slot = self;
        for index in indices {
            let Self::Array(values) = slot else {
                return Err("compile-time assignment indexes a scalar".into());
            };
            slot = values
                .get_mut(*index)
                .ok_or_else(|| "compile-time array assignment index is out of range".to_owned())?;
        }
        if slot.dimensions()? != value.dimensions()? {
            return Err("compile-time array assignment shape mismatch".into());
        }
        *slot = value;
        Ok(())
    }

    pub(super) fn dimensions(&self) -> EvalResult<Vec<usize>> {
        fn visit(value: &Value, depth: usize, count: &mut usize) -> EvalResult<Vec<usize>> {
            if depth >= MAX_DEPTH {
                return Err("compile-time array nesting exceeds the inspection limit".into());
            }
            *count += 1;
            if *count > MAX_ARRAY_ELEMENTS {
                return Err("compile-time array exceeds the inspection element limit".into());
            }
            match value {
                Value::Int(_) | Value::Unknown => Ok(Vec::new()),
                Value::Array(values) => {
                    let Some(first) = values.first() else {
                        return Err("empty compile-time arrays are unsupported".into());
                    };
                    let child = visit(first, depth + 1, count)?;
                    for value in &values[1..] {
                        if visit(value, depth + 1, count)? != child {
                            return Err("ragged compile-time array".into());
                        }
                    }
                    let mut dims = vec![values.len()];
                    dims.extend(child);
                    Ok(dims)
                }
            }
        }
        visit(self, 0, &mut 0)
    }
}

impl From<i128> for Value {
    fn from(value: i128) -> Self {
        Self::Int(value.into())
    }
}

#[cfg(test)]
pub(super) fn eval(tokens: &[Token], env: &Env) -> EvalResult<Value> {
    eval_with_calls(tokens, env, &mut |name, _| {
        Err(format!("unknown compile-time function {name}"))
    })
}

pub(super) fn eval_with_calls<F>(tokens: &[Token], env: &Env, call: &mut F) -> EvalResult<Value>
where
    F: FnMut(&str, &[Value]) -> EvalResult<Value>,
{
    if tokens.len() > MAX_STEPS {
        return Err("compile-time expression exceeds the inspection token limit".into());
    }
    let mut parser = Parser {
        tokens,
        cursor: 0,
        env,
        call,
        steps: 0,
        depth: 0,
    };
    let value = parser.conditional()?;
    if parser.cursor != tokens.len() {
        return Err(format!(
            "unsupported compile-time expression suffix {}",
            super::tokens_to_text(&tokens[parser.cursor..])
        ));
    }
    value.validate_initialized()?;
    Ok(value)
}

struct Parser<'a, F> {
    tokens: &'a [Token],
    cursor: usize,
    env: &'a Env,
    call: &'a mut F,
    steps: usize,
    depth: usize,
}

impl<F> Parser<'_, F>
where
    F: FnMut(&str, &[Value]) -> EvalResult<Value>,
{
    fn step(&mut self) -> EvalResult<()> {
        self.steps += 1;
        if self.steps > MAX_STEPS {
            return Err("compile-time expression exceeds the inspection step limit".into());
        }
        Ok(())
    }

    fn nested<T>(&mut self, f: impl FnOnce(&mut Self) -> EvalResult<T>) -> EvalResult<T> {
        if self.depth >= MAX_DEPTH {
            return Err("compile-time expression nesting exceeds the inspection limit".into());
        }
        self.depth += 1;
        let result = f(self);
        self.depth -= 1;
        result
    }

    fn symbol(&self, symbol: char) -> bool {
        self.tokens
            .get(self.cursor)
            .is_some_and(|token| token_is_symbol(token, symbol))
    }

    fn expect(&mut self, symbol: char) -> EvalResult<()> {
        if !self.symbol(symbol) {
            return Err(format!("compile-time expression expected `{symbol}`"));
        }
        self.cursor += 1;
        Ok(())
    }

    // Expression13 is outside all infix tiers, and each branch is Expression12.
    // Parenthesized expressions may contain another conditional; unparenthesized
    // chains leave an unexpected token and are refused by their enclosing parser.
    fn conditional(&mut self) -> EvalResult<Value> {
        let condition = self.binary(0)?;
        if !self.symbol('?') {
            // Preserve the original expression's steps and depth when no new
            // syntax is present, including expressions close to either limit.
            return Ok(condition);
        }
        self.step()?;
        self.cursor += 1;
        let if_true = self.binary(0)?;
        self.expect(':')?;
        let if_false = self.binary(0)?;
        let (Value::Int(condition), Value::Int(_), Value::Int(_)) =
            (&condition, &if_true, &if_false)
        else {
            return Err(
                "compile-time conditional requires initialized scalar condition and branches"
                    .into(),
            );
        };
        // Both branches are proven values before selection. This intentionally
        // refuses an unsupported or failing unselected branch; no lazy-evaluation
        // assumption is needed for the accepted pure, source-only subset.
        let prime = BigInt::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .expect("bn128 field modulus");
        Ok(if (condition % prime).is_zero() {
            if_false
        } else {
            if_true
        })
    }

    fn binary(&mut self, minimum_precedence: u8) -> EvalResult<Value> {
        self.nested(|parser| {
            let mut left = parser.unary()?;
            while let Some((operator, precedence, right_associative)) = parser.operator() {
                if precedence < minimum_precedence {
                    break;
                }
                parser.step()?;
                parser.cursor += 1;
                let right = parser.binary(if right_associative {
                    precedence
                } else {
                    precedence + 1
                })?;
                left = arithmetic_values(operator, &left, &right)?;
            }
            Ok(left)
        })
    }

    fn unary(&mut self) -> EvalResult<Value> {
        self.nested(|parser| {
            if parser.symbol('+') || parser.symbol('-') || parser.symbol('!') {
                parser.step()?;
                let operator = parser.tokens[parser.cursor].kind.clone();
                parser.cursor += 1;
                let value = parser.unary()?.scalar()?;
                return match operator {
                    TokenKind::Symbol('+') => Ok(Value::from(value)),
                    TokenKind::Symbol('-') => bounded(-BigInt::from(value)),
                    TokenKind::Symbol('!') => Ok(Value::from(i128::from(value == 0))),
                    _ => unreachable!(),
                };
            }
            parser.primary()
        })
    }

    fn primary(&mut self) -> EvalResult<Value> {
        self.step()?;
        let token = self
            .tokens
            .get(self.cursor)
            .ok_or_else(|| "compile-time expression is incomplete".to_owned())?
            .clone();
        self.cursor += 1;
        // Copy the environment reference so parsing an index can mutably borrow
        // the parser while the selected value continues to borrow the environment.
        let env = self.env;
        let mut value = match token.kind {
            TokenKind::Number(text) => {
                let text = text.replace('_', "");
                let value = if let Some(hex) =
                    text.strip_prefix("0x").or_else(|| text.strip_prefix("0X"))
                {
                    BigInt::parse_bytes(hex.as_bytes(), 16)
                } else {
                    BigInt::parse_bytes(text.as_bytes(), 10)
                }
                .ok_or_else(|| "unsupported compile-time integer literal".to_owned())?;
                Cow::Owned(Value::Int(value))
            }
            TokenKind::Identifier(name) if self.symbol('(') => {
                self.cursor += 1;
                let arguments = self.list(')')?;
                for argument in &arguments {
                    argument.validate_initialized()?;
                }
                let value = (self.call)(&name, &arguments)?;
                value.validate_initialized()?;
                Cow::Owned(value)
            }
            TokenKind::Identifier(name) => Cow::Borrowed(
                env.get(&name)
                    .ok_or_else(|| format!("unknown compile-time value {name}"))?,
            ),
            TokenKind::Symbol('(') => {
                let value = self.conditional()?;
                self.expect(')')?;
                Cow::Owned(value)
            }
            TokenKind::Symbol('[') => {
                let values = self.list(']')?;
                let value = Value::Array(values);
                value.dimensions()?;
                Cow::Owned(value)
            }
            _ => return Err("unsupported compile-time expression token".into()),
        };
        while self.symbol('[') {
            self.step()?;
            self.cursor += 1;
            let index = self.conditional()?.scalar()?;
            self.expect(']')?;
            let index = usize::try_from(index)
                .map_err(|_| "compile-time array index must be non-negative and platform-sized")?;
            value = select_index(value, index)?;
        }
        Ok(value.into_owned())
    }

    fn list(&mut self, closing: char) -> EvalResult<Vec<Value>> {
        let mut values = Vec::new();
        if self.symbol(closing) {
            self.cursor += 1;
            return Ok(values);
        }
        loop {
            if values.len() >= MAX_ARRAY_ELEMENTS {
                return Err("compile-time list exceeds the inspection element limit".into());
            }
            values.push(self.conditional()?);
            if self.symbol(closing) {
                self.cursor += 1;
                return Ok(values);
            }
            self.expect(',')?;
            if self.symbol(closing) {
                return Err("trailing commas in compile-time lists are unsupported".into());
            }
        }
    }

    fn operator(&self) -> Option<(&'static str, u8, bool)> {
        let op = match &self.tokens.get(self.cursor)?.kind {
            TokenKind::Operator(operator) => operator.as_str(),
            TokenKind::Symbol('<') => "<",
            TokenKind::Symbol('>') => ">",
            TokenKind::Symbol('+') => "+",
            TokenKind::Symbol('-') => "-",
            TokenKind::Symbol('*') => "*",
            TokenKind::Symbol('/') => "/",
            TokenKind::Symbol('\\') => "\\",
            TokenKind::Symbol('%') => "%",
            TokenKind::Symbol('&') => "&",
            TokenKind::Symbol('|') => "|",
            TokenKind::Symbol('^') => "^",
            _ => return None,
        };
        operator_table(op)
    }
}

/// Circom's local grammar (`parser/src/lang.lalrpop`, Expression12..3):
/// every infix tier is left associative, and comparisons share one tier below bits.
/// Keep this independent of the legacy discovery table to preserve existing output.
pub(super) fn operator_table(operator: &str) -> Option<(&'static str, u8, bool)> {
    let (operator, precedence) = match operator {
        "||" => ("||", 1),
        "&&" => ("&&", 2),
        "==" => ("==", 3),
        "!=" => ("!=", 3),
        "<" => ("<", 3),
        "<=" => ("<=", 3),
        ">" => (">", 3),
        ">=" => (">=", 3),
        "|" => ("|", 4),
        "^" => ("^", 5),
        "&" => ("&", 6),
        "<<" => ("<<", 7),
        ">>" => (">>", 7),
        "+" => ("+", 8),
        "-" => ("-", 8),
        "*" => ("*", 9),
        "/" => ("/", 9),
        "\\" => ("\\", 9),
        "%" => ("%", 9),
        "**" => ("**", 10),
        _ => return None,
    };
    Some((operator, precedence, false))
}

// Borrow array variables through every index; only the final selected value is
// cloned. Newly constructed arrays transfer the selected element without cloning.
fn select_index(value: Cow<'_, Value>, index: usize) -> EvalResult<Cow<'_, Value>> {
    match value {
        Cow::Borrowed(Value::Array(values)) => values.get(index).map(Cow::Borrowed),
        Cow::Owned(Value::Array(values)) => values.into_iter().nth(index).map(Cow::Owned),
        _ => return Err("compile-time indexing requires an array".into()),
    }
    .ok_or_else(|| "compile-time array index is out of range".into())
}

fn bounded(value: BigInt) -> EvalResult<Value> {
    if value.to_i128().is_none() {
        return Err("compile-time integer exceeds the exact i128 subset".into());
    }
    Ok(Value::Int(value))
}

/// Circom normalizes both operands into [0, p) before integer division or
/// remainder (circom_algebra/src/modular_arithmetic.rs, idiv/mod_op). The caller
/// enables this fallback only for explicit bn128 inspection. Keep full integer
/// values here; all other operations retain the exact i128 subset below.
fn integer_division_or_remainder(
    operator: &str,
    left: &BigInt,
    right: &BigInt,
) -> EvalResult<Value> {
    let prime = BigInt::parse_bytes(
        b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
        10,
    )
    .expect("bn128 field modulus");
    let left = ((left % &prime) + &prime) % &prime;
    let right = ((right % &prime) + &prime) % &prime;
    if right.is_zero() {
        return Err(
            "compile-time integer division or remainder by zero after field normalization".into(),
        );
    }
    Ok(Value::Int(if operator == "\\" {
        left / right
    } else {
        left % right
    }))
}

pub(super) fn arithmetic_values(operator: &str, left: &Value, right: &Value) -> EvalResult<Value> {
    if operator == "\\" || operator == "%" {
        let (Value::Int(left), Value::Int(right)) = (left, right) else {
            return Err(
                "compile-time integer division or remainder requires scalar operands".into(),
            );
        };
        return integer_division_or_remainder(operator, left, right);
    }
    arithmetic(operator, left.scalar()?, right.scalar()?)
}

pub(super) fn arithmetic(operator: &str, left: i128, right: i128) -> EvalResult<Value> {
    let boolean = |value: bool| Ok(Value::from(i128::from(value)));
    match operator {
        "||" => boolean(left != 0 || right != 0),
        "&&" => boolean(left != 0 && right != 0),
        "==" => boolean(left == right),
        "!=" => boolean(left != right),
        "<" => boolean(left < right),
        "<=" => boolean(left <= right),
        ">" => boolean(left > right),
        ">=" => boolean(left >= right),
        "+" => bounded(BigInt::from(left) + BigInt::from(right)),
        "-" => bounded(BigInt::from(left) - BigInt::from(right)),
        "*" => bounded(BigInt::from(left) * BigInt::from(right)),
        "/" => {
            let (left, right) = (BigInt::from(left), BigInt::from(right));
            if right.is_zero() || !(&left % &right).is_zero() {
                return Err(
                    "field division without a known modulus requires an exact integer quotient"
                        .into(),
                );
            }
            bounded(left / right)
        }
        "\\" | "%" => {
            integer_division_or_remainder(operator, &BigInt::from(left), &BigInt::from(right))
        }
        "&" | "|" | "^" | "<<" | ">>" if left < 0 || right < 0 => {
            Err("negative compile-time bit operands need a known field modulus".into())
        }
        "&" => Ok(Value::from(left & right)),
        "|" => Ok(Value::from(left | right)),
        "^" => Ok(Value::from(left ^ right)),
        "<<" | ">>" => {
            let shift = u32::try_from(right)
                .ok()
                .filter(|shift| *shift < 127)
                .ok_or_else(|| "compile-time shift exceeds the exact integer subset".to_owned())?;
            bounded(if operator == "<<" {
                BigInt::from(left) << shift
            } else {
                BigInt::from(left) >> shift
            })
        }
        "**" => {
            let power = u32::try_from(right)
                .ok()
                .filter(|power| *power <= 127)
                .ok_or_else(|| {
                    "compile-time exponent exceeds the exact integer subset".to_owned()
                })?;
            bounded(BigInt::from(left).pow(power))
        }
        _ => Err(format!("unsupported compile-time operator {operator}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evaluate(source: &str, env: &Env) -> EvalResult<Value> {
        eval(&super::super::lex(source).expect("tokens"), env)
    }

    #[test]
    fn array_literals_and_nested_indexing_are_exact() {
        let value = evaluate("[[1 + 2, 4], [5, 6 * 2]]", &Env::new()).unwrap();
        assert_eq!(value.dimensions().unwrap(), vec![2, 2]);
        assert_eq!(value.literal(), "[[3, 4], [5, 12]]");
        let env = Env::from([("x".into(), value)]);
        assert_eq!(evaluate("x[1][0] + x[0][1]", &env).unwrap(), Value::from(9));
        assert_eq!(evaluate("([7, 8])[0]", &env).unwrap(), Value::from(7));
    }

    #[test]
    fn refuses_ambiguous_arrays_and_indices() {
        for source in [
            "[]",
            "[[1], [2, 3]]",
            "[1, [2]]",
            "[1,]",
            "[1][-1]",
            "[1][1]",
            "3[0]",
        ] {
            assert!(evaluate(source, &Env::new()).is_err(), "{source}");
        }
        assert!(evaluate("[unknown]", &Env::new()).is_err());
    }

    #[test]
    fn uses_exact_arithmetic_and_refuses_field_dependent_guessing() {
        for (source, expected) in [
            ("(64 * 32) / 64", 32),
            ("-12 / 3", -4),
            ("9 % 4", 1),
            ("2 ** 3 ** 2", 64),
            ("4 << 2", 16),
            ("0x10 + 1_000", 1016),
        ] {
            assert_eq!(
                evaluate(source, &Env::new()).unwrap(),
                Value::from(expected)
            );
        }
        for source in [
            "5 / 2",
            "1 / 0",
            "-1 >> 1",
            "1 << 127",
            "2 ** 128",
            "170141183460469231731687303715884105727 + 1",
        ] {
            assert!(evaluate(source, &Env::new()).is_err(), "{source}");
        }
    }

    #[test]
    fn function_hook_receives_array_values_and_nested_arguments() {
        let tokens = super::super::lex("pick([[3, 5], [8, 13]], 1)[0]").unwrap();
        let mut names = Vec::new();
        let value = eval_with_calls(&tokens, &Env::new(), &mut |name, args| {
            names.push(name.to_owned());
            assert_eq!(args.len(), 2);
            let Value::Array(rows) = &args[0] else {
                panic!("array expected")
            };
            Ok(rows[args[1].scalar().unwrap() as usize].clone())
        })
        .unwrap();
        assert_eq!(value, Value::from(8));
        assert_eq!(names, vec!["pick"]);
        assert!(evaluate("missing(1)", &Env::new()).is_err());
    }

    #[test]
    fn large_constants_are_opaque_until_used_in_arithmetic() {
        let large = "21888242871839275222246405745257275088548364400416034343698204186575808495616";
        let value = evaluate(&format!("[{large}]"), &Env::new()).unwrap();
        assert_eq!(value.literal(), format!("[{large}]"));
        let env = Env::from([("x".into(), value)]);
        assert_eq!(evaluate("x[0]", &env).unwrap().literal(), large);
        assert!(evaluate("x[0] + 1", &env).is_err());
        assert!(evaluate("x[0] == x[0]", &env).is_err());
    }

    #[test]
    fn declared_arrays_refuse_uninitialized_values_and_check_assignment_shape() {
        let mut value = Value::uninitialized(&[2, 2]).unwrap();
        assert_eq!(value.dimensions().unwrap(), vec![2, 2]);
        assert!(value.validate_initialized().is_err());
        value.set_index(&[0, 1], Value::from(5)).unwrap();
        let env = Env::from([("x".into(), value.clone())]);
        assert_eq!(evaluate("x[0][1]", &env).unwrap(), Value::from(5));
        assert!(evaluate("x[0][0]", &env).is_err());
        assert!(evaluate("x", &env).is_err());
        assert!(value.set_index(&[2, 0], Value::from(1)).is_err());
        assert!(value.set_index(&[0], Value::from(1)).is_err());
        assert!(Value::uninitialized(&[100_000, 100_000]).is_err());
    }

    #[test]
    fn indexing_borrows_array_variables_until_the_selected_leaf() {
        let value = Value::Array(vec![Value::Array(vec![Value::from(3), Value::from(8)])]);
        let row = select_index(Cow::Borrowed(&value), 0).unwrap();
        assert!(matches!(row, Cow::Borrowed(_)));
        let leaf = select_index(row, 1).unwrap();
        let Value::Array(rows) = &value else {
            unreachable!()
        };
        let Value::Array(elements) = &rows[0] else {
            unreachable!()
        };
        let Cow::Borrowed(selected) = leaf else {
            panic!("selected value must still borrow")
        };
        assert!(std::ptr::eq(selected, &elements[1]));
        let env = Env::from([("x".into(), value)]);
        assert_eq!(evaluate("x[0][1]", &env).unwrap(), Value::from(8));
    }

    #[test]
    fn exponentiation_follows_circom_left_associativity() {
        assert_eq!(
            evaluate("2 ** 3 ** 2", &Env::new()).unwrap(),
            Value::from(64)
        );
    }

    #[test]
    fn bitwise_operators_bind_more_tightly_than_comparisons() {
        assert_eq!(evaluate("2 & 1 == 0", &Env::new()).unwrap(), Value::from(1));
    }

    #[test]
    fn equality_and_ordering_share_a_left_associative_tier() {
        assert_eq!(evaluate("2 == 1 < 1", &Env::new()).unwrap(), Value::from(1));
    }

    #[test]
    fn round2_integer_division_uses_the_nonnegative_quotient() {
        for (source, expected) in [(r"5 \ 2", 2), (r"3 \ 5", 0), (r"0 \ 7", 0), (r"7 \ 1", 7)] {
            assert_eq!(
                evaluate(source, &Env::new()).unwrap(),
                Value::from(expected)
            );
        }
        // Field division stays distinct; a fractional field quotient is refused.
        assert!(evaluate("5 / 2", &Env::new()).is_err());
        assert_eq!(evaluate("6 / 2", &Env::new()).unwrap(), Value::from(3));
    }

    #[test]
    fn round2_integer_division_and_remainder_obey_the_euclidean_identity() {
        for left in 0..32i128 {
            for right in 1..16i128 {
                let quotient = arithmetic("\\", left, right).unwrap().scalar().unwrap();
                let remainder = arithmetic("%", left, right).unwrap().scalar().unwrap();
                assert_eq!(left, right * quotient + remainder);
                assert!(remainder >= 0 && remainder < right);
            }
        }
    }

    #[test]
    fn round2_integer_division_matches_circom_normalization_at_subset_boundaries() {
        let prime = BigInt::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .unwrap();
        assert!(prime > BigInt::from(i128::MAX));
        for left in [0i128, 1, 2, i128::MAX - 1, i128::MAX] {
            for right in [1i128, 2, 3, i128::MAX] {
                let normalized_left = ((BigInt::from(left) % &prime) + &prime) % &prime;
                let normalized_right = ((BigInt::from(right) % &prime) + &prime) % &prime;
                assert_eq!(
                    arithmetic("\\", left, right).unwrap(),
                    Value::Int(&normalized_left / &normalized_right)
                );
                assert_eq!(
                    arithmetic("%", left, right).unwrap(),
                    Value::Int(&normalized_left % &normalized_right)
                );
            }
        }
    }

    #[test]
    fn round2_integer_division_and_remainder_normalize_negative_and_large_operands() {
        let prime = BigInt::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .unwrap();
        assert_eq!(
            evaluate(r"-1 \ 2", &Env::new()).unwrap(),
            Value::Int((&prime - 1) / 2)
        );
        assert_eq!(evaluate("-1 % 2", &Env::new()).unwrap(), Value::from(0));
        assert_eq!(evaluate(r"5 \ -2", &Env::new()).unwrap(), Value::from(0));
        assert_eq!(evaluate("5 % -2", &Env::new()).unwrap(), Value::from(5));
        assert_eq!(evaluate(r"-1 \ -2", &Env::new()).unwrap(), Value::from(1));
        assert_eq!(evaluate("-1 % -2", &Env::new()).unwrap(), Value::from(1));
        let large_left = &prime * 2 + BigInt::from(7);
        let large_right = &prime + BigInt::from(2);
        assert_eq!(
            evaluate(&format!(r"{large_left} \ {large_right}"), &Env::new()).unwrap(),
            Value::from(3)
        );
        assert_eq!(
            evaluate(&format!("{large_left} % {large_right}"), &Env::new()).unwrap(),
            Value::from(1)
        );
        // Large canonical results may be passed on, but unrelated arithmetic
        // still refuses to guess outside the original exact i128 subset.
        assert!(evaluate(r"(-1 \ 2) + 1", &Env::new()).is_err());
        assert!(evaluate("5 / 2", &Env::new()).is_err());
    }

    #[test]
    fn round2_integer_division_and_remainder_reject_zero_after_normalization() {
        let prime = BigInt::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .unwrap();
        for operator in ["\\", "%"] {
            for divisor in [BigInt::from(0), prime.clone(), &prime * 2, -&prime] {
                let env = Env::from([("divisor".into(), Value::Int(divisor))]);
                assert!(evaluate(&format!("1 {operator} divisor"), &env)
                    .unwrap_err()
                    .contains("zero"));
            }
            assert!(arithmetic_values(
                operator,
                &Value::Array(vec![Value::from(1)]),
                &Value::from(2)
            )
            .is_err());
        }
    }

    #[test]
    fn round2_integer_division_shares_circom_multiplicative_precedence() {
        for (source, expected) in [
            (r"20 \ 3 * 2", 12),
            (r"20 * 3 \ 4", 15),
            (r"20 \ 3 % 4", 2),
            (r"20 % 7 \ 2", 3),
            (r"20 \ 3 \ 2", 3),
            (r"12 \ 2 ** 2", 3),
            (r"12 \ 2 + 3", 9),
        ] {
            assert_eq!(
                evaluate(source, &Env::new()).unwrap(),
                Value::from(expected)
            );
        }
    }

    #[test]
    fn round2_integer_division_and_remainder_can_index_arrays() {
        let env = Env::from([(
            "x".into(),
            Value::Array(vec![Value::from(3), Value::from(5), Value::from(8)]),
        )]);
        assert_eq!(evaluate(r"x[5 \ 2]", &env).unwrap(), Value::from(8));
        assert_eq!(evaluate("x[5 % 3]", &env).unwrap(), Value::from(8));
    }

    #[test]
    fn round2_conditional_selects_exact_scalar_branches_with_lowest_precedence() {
        for (source, expected) in [
            ("0 ? 148 : 4", 4),
            ("1 ? 148 : 4", 148),
            ("0 || 1 ? 2 + 3 * 4 : 7", 14),
            ("2 & 1 == 0 ? 11 : 13", 11),
            ("3 > 5 ? 3 : 5", 5),
        ] {
            assert_eq!(
                evaluate(source, &Env::new()).unwrap(),
                Value::from(expected)
            );
        }
        let mut env = Env::from([
            ("s".into(), Value::from(0)),
            ("nsegments".into(), Value::from(2)),
            ("nlastsegment".into(), Value::from(37)),
        ]);
        let source = "(s < nsegments-1) ? 148 : nlastsegment";
        assert_eq!(evaluate(source, &env).unwrap(), Value::from(148));
        env.insert("s".into(), Value::from(1));
        assert_eq!(evaluate(source, &env).unwrap(), Value::from(37));
    }

    #[test]
    fn round2_conditional_uses_canonical_bn128_truth_without_i128_conversion() {
        let prime = BigInt::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .unwrap();
        for (condition, expected) in [
            (BigInt::from(0), 7),
            (prime.clone(), 7),
            (-&prime, 7),
            (&prime * 2, 7),
            (&prime + 1, 5),
            (BigInt::from(-1), 5),
        ] {
            let env = Env::from([("condition".into(), Value::Int(condition))]);
            assert_eq!(
                evaluate("condition ? 5 : 7", &env).unwrap(),
                Value::from(expected)
            );
        }
        let large = &prime - 1;
        assert_eq!(
            evaluate(&format!("1 ? {large} : 0"), &Env::new()).unwrap(),
            Value::Int(large)
        );
    }

    #[test]
    fn round2_conditional_refuses_errors_even_in_the_unselected_branch() {
        for source in [
            "1 ? 5 : missing",
            "0 ? missing : 7",
            "1 ? 5 : 1 / 0",
            "0 ? 1 / 0 : 7",
            "1 ? 5 : 5 / 2",
            "0 ? missing_function(1) : 7",
        ] {
            assert!(evaluate(source, &Env::new()).is_err(), "{source}");
        }
    }

    #[test]
    fn round2_conditional_refuses_arrays_and_uninitialized_values_in_every_position() {
        let env = Env::from([("unknown".into(), Value::Unknown)]);
        for source in [
            "[1] ? 5 : 7",
            "1 ? [5] : 7",
            "0 ? [5] : 7",
            "1 ? 5 : [7]",
            "0 ? 5 : [7]",
            "1 ? [5] : [7]",
            "unknown ? 5 : 7",
            "0 ? unknown : 7",
            "1 ? 5 : unknown",
        ] {
            assert!(evaluate(source, &env).is_err(), "{source}");
        }
    }

    #[test]
    fn round2_conditional_allows_parenthesized_nesting_but_refuses_bare_chains() {
        for (source, expected) in [
            ("1 ? (0 ? 2 : 3) : 4", 3),
            ("0 ? 2 : (1 ? 3 : 4)", 3),
            ("(0 ? 0 : 1) ? 3 : 4", 3),
            ("2 * (1 ? 3 : 4)", 6),
        ] {
            assert_eq!(
                evaluate(source, &Env::new()).unwrap(),
                Value::from(expected)
            );
        }
        for source in [
            "1 ? 0 ? 2 : 3 : 4",
            "0 ? 2 : 1 ? 3 : 4",
            "1 ? 2",
            "1 ? : 3",
            "1 ? 2 :",
            "1 : 2",
        ] {
            assert!(evaluate(source, &Env::new()).is_err(), "{source}");
        }
    }

    #[test]
    fn round2_conditional_works_in_argument_array_and_index_expression_contexts() {
        let env = Env::from([(
            "x".into(),
            Value::Array(vec![Value::from(3), Value::from(5)]),
        )]);
        assert_eq!(evaluate("x[1 ? 0 : 1]", &env).unwrap(), Value::from(3));
        assert_eq!(
            evaluate("[1 ? 3 : 5, 0 ? 7 : 11]", &env).unwrap().literal(),
            "[3, 11]"
        );
        let tokens = super::super::lex("pick(0 ? 3 : 5, 1 ? 7 : 11)").unwrap();
        let result = eval_with_calls(&tokens, &env, &mut |name, arguments| {
            assert_eq!(name, "pick");
            assert_eq!(arguments, &[Value::from(5), Value::from(7)]);
            Ok(arguments[1].clone())
        })
        .unwrap();
        assert_eq!(result, Value::from(7));
    }

    #[test]
    fn round2_conditional_checks_both_pure_call_results_before_selection() {
        let tokens = super::super::lex("1 ? first() : second()").unwrap();
        let mut called = Vec::new();
        let result = eval_with_calls(&tokens, &Env::new(), &mut |name, arguments| {
            assert!(arguments.is_empty());
            called.push(name.to_owned());
            Ok(Value::from(if name == "first" { 5 } else { 7 }))
        })
        .unwrap();
        assert_eq!(result, Value::from(5));
        assert_eq!(called, vec!["first", "second"]);
        assert!(eval_with_calls(&tokens, &Env::new(), &mut |name, _| {
            if name == "second" {
                Err("unsupported unselected branch".into())
            } else {
                Ok(Value::from(5))
            }
        })
        .is_err());
    }

    #[test]
    fn round2_conditional_keeps_existing_expression_budget_and_bounds_new_nesting() {
        let tokens = super::super::lex("1 + 2 * 3").unwrap();
        let env = Env::new();
        let mut call = |_: &str, _: &[Value]| Err("no calls".into());
        let mut parser = Parser {
            tokens: &tokens,
            cursor: 0,
            env: &env,
            call: &mut call,
            steps: 0,
            depth: 0,
        };
        let direct = parser.binary(0).unwrap();
        let old_steps = parser.steps;
        parser.cursor = 0;
        parser.steps = 0;
        let conditional = parser.conditional().unwrap();
        assert_eq!(conditional, direct);
        assert_eq!(parser.steps, old_steps);
        let mut source = "1".to_owned();
        for _ in 0..100 {
            source = format!("1 ? ({source}) : 0");
        }
        assert!(evaluate(&source, &env).unwrap_err().contains("nesting"));
    }

    #[test]
    fn bounded_expression_recursion_fails_closed() {
        let source = format!("{}1{}", "(".repeat(100), ")".repeat(100));
        assert!(evaluate(&source, &Env::new())
            .unwrap_err()
            .contains("nesting"));
    }
}
