//! Bounded, source-evaluated pure functions for target inspection only.

use std::{
    collections::{HashMap, HashSet},
    path::PathBuf,
};

use super::{
    compile_time::{self, Env, Value},
    find_matching, find_statement_end, lex, split_top_level, token_identifier, token_is_identifier,
    token_is_symbol, Token, TokenKind,
};

type EvalResult<T> = std::result::Result<T, String>;
const MAX_FUNCTION_STEPS: usize = 100_000;
const MAX_CALL_DEPTH: usize = 32;
const MAX_SYNTAX_DEPTH: usize = 64;

#[derive(Clone)]
struct Definition {
    parameters: Vec<String>,
    body: Vec<Statement>,
    calls: Vec<String>,
    context: SourceContext,
}

#[derive(Clone)]
struct SourceContext {
    path: PathBuf,
    function: String,
    line: usize,
}

fn source_error(context: &SourceContext, line: usize, reason: String) -> String {
    if reason.starts_with("compile-time source ") {
        return reason;
    }
    format!(
        "compile-time source {}:{line}: function {}: {reason}",
        context.path.display(),
        context.function
    )
}

#[derive(Clone)]
struct Place {
    name: String,
    indices: Vec<Vec<Token>>,
}

#[derive(Clone)]
enum Statement {
    Located {
        line: usize,
        inner: Box<Statement>,
    },
    Assert(Vec<Token>),
    CheckLog(Vec<Vec<Token>>),
    Variable {
        name: String,
        dimensions: Vec<Vec<Token>>,
        initial: Option<Vec<Token>>,
    },
    Assign {
        place: Place,
        operator: String,
        expression: Vec<Token>,
    },
    Return(Vec<Token>),
    If {
        condition: Vec<Token>,
        yes: Vec<Statement>,
        no: Vec<Statement>,
    },
    For {
        initial: Box<Statement>,
        condition: Vec<Token>,
        update: Box<Statement>,
        body: Vec<Statement>,
    },
    While {
        condition: Vec<Token>,
        body: Vec<Statement>,
    },
    Block(Vec<Statement>),
}

pub(super) struct Functions {
    definitions: HashMap<String, Vec<EvalResult<Definition>>>,
    remaining: usize,
    depth: usize,
    pure: HashSet<String>,
    contexts: Vec<SourceContext>,
}

impl Functions {
    /// Unsupported and ambiguous definitions are retained; only a call rejects them.
    pub(super) fn from_sources(sources: &[(PathBuf, String)]) -> EvalResult<Self> {
        let mut definitions: HashMap<String, Vec<EvalResult<Definition>>> = HashMap::new();
        for (path, source) in sources {
            let tokens = lex(source)
                .map_err(|(line, reason)| format!("{}:{line}: {reason}", path.display()))?;
            let mut cursor = 0;
            while cursor < tokens.len() {
                if token_is_identifier(&tokens[cursor], "function") {
                    let Some(name) = tokens.get(cursor + 1).and_then(token_identifier) else {
                        cursor += 1;
                        continue;
                    };
                    let open = cursor + 2;
                    let close = tokens
                        .get(open)
                        .filter(|token| token_is_symbol(token, '('))
                        .and_then(|_| find_matching(&tokens, open, '(', ')'));
                    let body_open = close.map(|close| close + 1);
                    let body_close = body_open
                        .filter(|open| {
                            tokens
                                .get(*open)
                                .is_some_and(|token| token_is_symbol(token, '{'))
                        })
                        .and_then(|open| find_matching(&tokens, open, '{', '}'));
                    let parsed = match (close, body_open, body_close) {
                        (Some(close), Some(body_open), Some(body_close)) => parse_definition(
                            &tokens[open + 1..close],
                            &tokens[body_open + 1..body_close],
                            SourceContext {
                                path: path.clone(),
                                function: name.into(),
                                line: tokens[cursor].line,
                            },
                        ),
                        _ => Err("unsupported function header or unbalanced body".into()),
                    }
                    .map_err(|reason| {
                        source_error(
                            &SourceContext {
                                path: path.clone(),
                                function: name.into(),
                                line: tokens[cursor].line,
                            },
                            tokens[cursor].line,
                            reason,
                        )
                    });
                    definitions.entry(name.into()).or_default().push(parsed);
                    cursor = body_close.map_or(cursor + 1, |close| close + 1);
                    continue;
                }
                // Do not interpret function-looking tokens inside another top-level body.
                if token_is_symbol(&tokens[cursor], '{') {
                    if let Some(close) = find_matching(&tokens, cursor, '{', '}') {
                        cursor = close + 1;
                        continue;
                    }
                }
                cursor += 1;
            }
        }
        Ok(Self {
            definitions,
            remaining: MAX_FUNCTION_STEPS,
            depth: 0,
            pure: HashSet::new(),
            contexts: Vec::new(),
        })
    }

    /// The budget is shared by every call and loop for this source closure.
    pub(super) fn eval(&mut self, tokens: &[Token], env: &Env) -> EvalResult<Value> {
        self.consume(tokens.len().max(1))?;
        let result =
            compile_time::eval_with_calls(tokens, env, &mut |name, args| self.call(name, args));
        result.map_err(|reason| match self.contexts.last() {
            Some(context) => source_error(
                context,
                tokens.first().map_or(context.line, |token| token.line),
                reason,
            ),
            None => reason,
        })
    }

    fn consume(&mut self, steps: usize) -> EvalResult<()> {
        if steps > self.remaining {
            self.remaining = 0;
            return Err("compile-time function inspection budget exhausted".into());
        }
        self.remaining -= steps;
        Ok(())
    }

    fn ensure_pure(&mut self, name: &str) -> EvalResult<()> {
        if self.pure.contains(name) {
            return Ok(());
        }
        let mut pending = vec![name.to_owned()];
        let mut visited = HashSet::new();
        while let Some(name) = pending.pop() {
            if self.pure.contains(&name) || !visited.insert(name.clone()) {
                continue;
            }
            self.consume(1)?;
            let definitions = self
                .definitions
                .get(&name)
                .ok_or_else(|| format!("unknown compile-time function {name}"))?;
            let [definition] = definitions.as_slice() else {
                return Err(format!("ambiguous compile-time function {name}"));
            };
            let definition = definition.as_ref().map_err(Clone::clone)?;
            pending.extend(definition.calls.iter().cloned());
        }
        self.pure.extend(visited);
        Ok(())
    }

    fn call(&mut self, name: &str, arguments: &[Value]) -> EvalResult<Value> {
        self.consume(1)?;
        self.ensure_pure(name)?;
        if self.depth >= MAX_CALL_DEPTH {
            return Err(
                "compile-time function recursion exceeds the inspection depth limit".into(),
            );
        }
        let definitions = self
            .definitions
            .get(name)
            .ok_or_else(|| format!("unknown compile-time function {name}"))?;
        let [definition] = definitions.as_slice() else {
            return Err(format!("ambiguous compile-time function {name}"));
        };
        let definition = definition.clone()?;
        if definition.parameters.len() != arguments.len() {
            return Err(format!(
                "compile-time function {name} argument count mismatch"
            ));
        }
        for value in arguments {
            value.validate_initialized()?;
        }
        let mut locals = Locals {
            env: definition
                .parameters
                .into_iter()
                .zip(arguments.iter().cloned())
                .collect(),
            scopes: Vec::new(),
        };
        self.depth += 1;
        self.contexts.push(definition.context.clone());
        let result = self.block(&definition.body, &mut locals).and_then(|value| {
            value.ok_or_else(|| format!("compile-time function {name} has no return value"))
        });
        self.depth -= 1;
        self.contexts.pop();
        result.map_err(|reason| source_error(&definition.context, definition.context.line, reason))
    }

    fn block(
        &mut self,
        statements: &[Statement],
        locals: &mut Locals,
    ) -> EvalResult<Option<Value>> {
        locals.scopes.push(HashSet::new());
        let result = (|| {
            for statement in statements {
                if let Some(value) = self.statement(statement, locals)? {
                    return Ok(Some(value));
                }
            }
            Ok(None)
        })();
        locals.pop_scope();
        result
    }

    fn statement(
        &mut self,
        statement: &Statement,
        locals: &mut Locals,
    ) -> EvalResult<Option<Value>> {
        if let Statement::Located { line, inner } = statement {
            return self
                .statement(inner, locals)
                .map_err(|reason| match self.contexts.last() {
                    Some(context) => source_error(context, *line, reason),
                    None => reason,
                });
        }
        self.consume(1)?;
        match statement {
            Statement::Located { .. } => unreachable!("located statement handled above"),
            Statement::Assert(expression) => {
                let value = self.eval(expression, &locals.env)?;
                let Value::Int(value) = value else {
                    return Err("compile-time assert condition must be a scalar".into());
                };
                let prime = num_bigint::BigInt::parse_bytes(b"21888242871839275222246405745257275088548364400416034343698204186575808495617", 10).expect("bn128 field modulus");
                if value % prime == num_bigint::BigInt::from(0) {
                    return Err("compile-time assert failed".into());
                }
                Ok(None)
            }
            Statement::CheckLog(arguments) => {
                for argument in arguments {
                    if matches!(
                        argument.as_slice(),
                        [Token {
                            kind: TokenKind::StringLiteral(_),
                            ..
                        }]
                    ) {
                        continue;
                    }
                    if !matches!(self.eval(argument, &locals.env)?, Value::Int(_)) {
                        return Err(
                            "compile-time log argument must be a string literal or scalar".into(),
                        );
                    }
                }
                Ok(None)
            }
            Statement::Variable {
                name,
                dimensions,
                initial,
            } => {
                let dims = dimensions.iter().map(|expression| {
                    usize::try_from(self.eval(expression, &locals.env)?.scalar()?)
                        .map_err(|_| "compile-time variable dimension must be non-negative and platform-sized".into())
                }).collect::<EvalResult<Vec<_>>>()?;
                let value = match initial {
                    Some(expression) => self.eval(expression, &locals.env)?,
                    None => Value::uninitialized(&dims)?,
                };
                if value.dimensions()? != dims {
                    return Err("compile-time variable initializer shape mismatch".into());
                }
                locals.declare(name, value)?;
                Ok(None)
            }
            Statement::Assign {
                place,
                operator,
                expression,
            } => {
                let indices = place.indices.iter().map(|index| {
                    usize::try_from(self.eval(index, &locals.env)?.scalar()?)
                        .map_err(|_| "compile-time assignment index must be non-negative and platform-sized".into())
                }).collect::<EvalResult<Vec<_>>>()?;
                let right = self.eval(expression, &locals.env)?;
                let target = locals.env.get_mut(&place.name).ok_or_else(|| {
                    format!("assignment to unknown compile-time variable {}", place.name)
                })?;
                let value = if operator == "=" {
                    right
                } else {
                    let mut previous: &Value = target;
                    for index in &indices {
                        let Value::Array(values) = previous else {
                            return Err("compile-time compound assignment indexes a scalar".into());
                        };
                        previous = values.get(*index).ok_or_else(|| {
                            "compile-time assignment index is out of range".to_owned()
                        })?;
                    }
                    compile_time::arithmetic_values(operator, previous, &right)?
                };
                target.set_index(&indices, value)?;
                Ok(None)
            }
            Statement::Return(expression) => Ok(Some(self.eval(expression, &locals.env)?)),
            Statement::If { condition, yes, no } => {
                let truth = self.eval(condition, &locals.env)?.scalar()? != 0;
                self.block(if truth { yes } else { no }, locals)
            }
            Statement::For {
                initial,
                condition,
                update,
                body,
            } => {
                locals.scopes.push(HashSet::new());
                let result = (|| {
                    self.statement(initial, locals)?;
                    loop {
                        self.consume(1)?;
                        if self.eval(condition, &locals.env)?.scalar()? == 0 {
                            return Ok(None);
                        }
                        if let Some(value) = self.block(body, locals)? {
                            return Ok(Some(value));
                        }
                        self.statement(update, locals)?;
                    }
                })();
                locals.pop_scope();
                result
            }
            Statement::While { condition, body } => loop {
                self.consume(1)?;
                if self.eval(condition, &locals.env)?.scalar()? == 0 {
                    return Ok(None);
                }
                if let Some(value) = self.block(body, locals)? {
                    return Ok(Some(value));
                }
            },
            Statement::Block(body) => self.block(body, locals),
        }
    }
}

struct Locals {
    env: Env,
    scopes: Vec<HashSet<String>>,
}

impl Locals {
    fn declare(&mut self, name: &str, value: Value) -> EvalResult<()> {
        if self.env.contains_key(name) {
            return Err(format!(
                "compile-time variable shadowing or duplicate declaration {name} is unsupported"
            ));
        }
        self.scopes
            .last_mut()
            .expect("statement execution has a scope")
            .insert(name.into());
        self.env.insert(name.into(), value);
        Ok(())
    }

    fn pop_scope(&mut self) {
        for name in self.scopes.pop().expect("scope exists") {
            self.env.remove(&name);
        }
    }
}

fn parse_definition(
    parameters: &[Token],
    body: &[Token],
    context: SourceContext,
) -> EvalResult<Definition> {
    let mut names = Vec::new();
    for group in split_top_level(parameters, ',')? {
        let [token] = group.as_slice() else {
            return Err("unsupported function parameter declaration".into());
        };
        let name = token_identifier(token).ok_or("function parameter must be an identifier")?;
        if names.iter().any(|existing| existing == name) {
            return Err("duplicate function parameter".into());
        }
        names.push(name.to_owned());
    }
    // Validate the complete body, including unreachable branches, before execution.
    if let Some(token) = body.iter().find(|token| {
        token_identifier(token).is_some_and(|name| ["signal", "component", "bus", "template", "function"].contains(&name))
        || matches!(&token.kind, TokenKind::Operator(op) if ["<==", "==>", "===", "<--", "-->"].contains(&op.as_str()))
    }) {
        return Err(source_error(&context, token.line, "compile-time function contains signals, components, constraints, or unsupported statements".into()));
    }
    let mut calls = body
        .windows(2)
        .filter_map(|pair| {
            let name = token_identifier(&pair[0])?;
            (token_is_symbol(&pair[1], '(')
                && !["if", "for", "while", "return", "var", "assert", "log"].contains(&name))
            .then(|| name.to_owned())
        })
        .collect::<Vec<_>>();
    calls.sort();
    calls.dedup();
    let body = BodyParser {
        tokens: body,
        cursor: 0,
        depth: 0,
        context: &context,
    }
    .all()?;
    Ok(Definition {
        parameters: names,
        calls,
        body,
        context,
    })
}

struct BodyParser<'a> {
    tokens: &'a [Token],
    cursor: usize,
    depth: usize,
    context: &'a SourceContext,
}

impl BodyParser<'_> {
    fn all(&mut self) -> EvalResult<Vec<Statement>> {
        let mut statements = Vec::new();
        while self.cursor < self.tokens.len() {
            if token_is_symbol(&self.tokens[self.cursor], ';') {
                self.cursor += 1;
                continue;
            }
            statements.push(self.one()?);
        }
        Ok(statements)
    }

    fn body(&mut self) -> EvalResult<Vec<Statement>> {
        if self.depth >= MAX_SYNTAX_DEPTH {
            return Err("compile-time function syntax nesting limit".into());
        }
        self.depth += 1;
        let result = self.one().map(|statement| match statement {
            Statement::Block(body) => body,
            Statement::Located { line, inner } => match *inner {
                Statement::Block(body) => body,
                other => vec![Statement::Located {
                    line,
                    inner: Box::new(other),
                }],
            },
            other => vec![other],
        });
        self.depth -= 1;
        result
    }

    fn condition(&mut self) -> EvalResult<Vec<Token>> {
        let open = self.cursor;
        if !self
            .tokens
            .get(open)
            .is_some_and(|token| token_is_symbol(token, '('))
        {
            return Err("compile-time control flow needs a parenthesized condition".into());
        }
        let close = find_matching(self.tokens, open, '(', ')')
            .ok_or("unbalanced compile-time condition")?;
        let condition = self.tokens[open + 1..close].to_vec();
        self.cursor = close + 1;
        Ok(condition)
    }

    fn one(&mut self) -> EvalResult<Statement> {
        let line = self
            .tokens
            .get(self.cursor)
            .map_or(self.context.line, |token| token.line);
        self.one_unlocated()
            .map(|inner| Statement::Located {
                line,
                inner: Box::new(inner),
            })
            .map_err(|reason| source_error(self.context, line, reason))
    }

    fn one_unlocated(&mut self) -> EvalResult<Statement> {
        let token = self
            .tokens
            .get(self.cursor)
            .ok_or("compile-time statement is incomplete")?;
        if token_is_symbol(token, '{') {
            let close = find_matching(self.tokens, self.cursor, '{', '}')
                .ok_or("unbalanced compile-time block")?;
            if self.depth >= MAX_SYNTAX_DEPTH {
                return Err("compile-time function syntax nesting limit".into());
            }
            let body = BodyParser {
                tokens: &self.tokens[self.cursor + 1..close],
                cursor: 0,
                depth: self.depth + 1,
                context: self.context,
            }
            .all()?;
            self.cursor = close + 1;
            return Ok(Statement::Block(body));
        }
        if token_is_identifier(token, "if") {
            self.cursor += 1;
            let condition = self.condition()?;
            validate_expression(&condition)?;
            let yes = self.body()?;
            let no = if self
                .tokens
                .get(self.cursor)
                .is_some_and(|token| token_is_identifier(token, "else"))
            {
                self.cursor += 1;
                self.body()?
            } else {
                Vec::new()
            };
            return Ok(Statement::If { condition, yes, no });
        }
        if token_is_identifier(token, "for") {
            self.cursor += 1;
            let header = self.condition()?;
            let groups = split_top_level(&header, ';')?;
            let [initial, condition, update] = groups.as_slice() else {
                return Err("compile-time for needs three clauses".into());
            };
            let initial = parse_simple(initial)?;
            if !matches!(
                initial,
                Statement::Variable { .. } | Statement::Assign { .. }
            ) {
                return Err("unsupported compile-time for initializer".into());
            }
            validate_expression(condition)?;
            let update = parse_simple(update)?;
            if !matches!(update, Statement::Assign { .. }) {
                return Err("unsupported compile-time for update".into());
            }
            let body = self.body()?;
            return Ok(Statement::For {
                initial: Box::new(Statement::Located {
                    line: groups[0][0].line,
                    inner: Box::new(initial),
                }),
                condition: condition.clone(),
                update: Box::new(Statement::Located {
                    line: groups[2][0].line,
                    inner: Box::new(update),
                }),
                body,
            });
        }
        if token_is_identifier(token, "while") {
            self.cursor += 1;
            let condition = self.condition()?;
            validate_expression(&condition)?;
            let body = self.body()?;
            return Ok(Statement::While { condition, body });
        }
        let end = find_statement_end(self.tokens, self.cursor)
            .ok_or("compile-time statement lacks a semicolon")?;
        let statement = &self.tokens[self.cursor..end];
        self.cursor = end + 1;
        if statement
            .first()
            .is_some_and(|token| token_is_identifier(token, "return"))
        {
            let expression = statement[1..].to_vec();
            validate_expression(&expression)?;
            return Ok(Statement::Return(expression));
        }
        if statement.first().is_some_and(|token| {
            token_is_identifier(token, "assert") || token_is_identifier(token, "log")
        }) {
            if !statement
                .get(1)
                .is_some_and(|token| token_is_symbol(token, '('))
            {
                return Err("compile-time assert/log needs parenthesized arguments".into());
            }
            let close =
                find_matching(statement, 1, '(', ')').ok_or("unbalanced assert/log arguments")?;
            if close + 1 != statement.len() {
                return Err("trailing assert/log syntax is unsupported".into());
            }
            let arguments = split_top_level(&statement[2..close], ',')?;
            if arguments.is_empty() || arguments.iter().any(Vec::is_empty) {
                return Err("compile-time assert/log needs nonempty arguments".into());
            }
            if token_is_identifier(&statement[0], "assert") {
                let [expression] = arguments.as_slice() else {
                    return Err("compile-time assert needs exactly one argument".into());
                };
                validate_expression(expression)?;
                return Ok(Statement::Assert(expression.clone()));
            }
            for argument in &arguments {
                if !matches!(
                    argument.as_slice(),
                    [Token {
                        kind: TokenKind::StringLiteral(_),
                        ..
                    }]
                ) {
                    validate_expression(argument)?;
                }
            }
            return Ok(Statement::CheckLog(arguments));
        }
        parse_simple(statement)
    }
}

fn parse_place(tokens: &[Token], mut cursor: usize) -> EvalResult<(Place, usize)> {
    let name = tokens
        .get(cursor)
        .and_then(token_identifier)
        .ok_or("compile-time assignment needs a variable")?
        .to_owned();
    cursor += 1;
    let mut indices = Vec::new();
    while tokens
        .get(cursor)
        .is_some_and(|token| token_is_symbol(token, '['))
    {
        let close = find_matching(tokens, cursor, '[', ']')
            .ok_or("unbalanced compile-time variable index")?;
        let index = tokens[cursor + 1..close].to_vec();
        validate_expression(&index)?;
        indices.push(index);
        cursor = close + 1;
    }
    Ok((Place { name, indices }, cursor))
}

fn parse_simple(tokens: &[Token]) -> EvalResult<Statement> {
    if tokens
        .first()
        .is_some_and(|token| token_is_identifier(token, "var"))
    {
        let (place, cursor) = parse_place(tokens, 1)?;
        let initial = if cursor == tokens.len() {
            None
        } else {
            if !token_is_symbol(&tokens[cursor], '=') {
                return Err("unsupported compile-time variable declaration".into());
            }
            let expression = tokens[cursor + 1..].to_vec();
            validate_expression(&expression)?;
            Some(expression)
        };
        return Ok(Statement::Variable {
            name: place.name,
            dimensions: place.indices,
            initial,
        });
    }
    let (place, cursor) = parse_place(tokens, 0)?;
    let rest = &tokens[cursor..];
    let (operator, expression) = match rest {
        [Token {
            kind: TokenKind::Operator(op),
            ..
        }] if op == "++" || op == "--" => (
            if op == "++" { "+" } else { "-" }.to_owned(),
            lex("1").expect("literal token"),
        ),
        [first, expression @ ..] if token_is_symbol(first, '=') => {
            ("=".into(), expression.to_vec())
        }
        [operator, equal, expression @ ..] if token_is_symbol(equal, '=') => {
            let operator = super::token_to_text(operator);
            if ![
                "+", "-", "*", "/", "\\", "%", "&", "|", "^", "<<", ">>", "**",
            ]
            .contains(&operator.as_str())
            {
                return Err("unsupported compile-time compound assignment".into());
            }
            (operator, expression.to_vec())
        }
        _ => return Err("unsupported statement in compile-time function".into()),
    };
    validate_expression(&expression)?;
    Ok(Statement::Assign {
        place,
        operator,
        expression,
    })
}

fn validate_expression(tokens: &[Token]) -> EvalResult<()> {
    let mut parser = Syntax {
        tokens,
        cursor: 0,
        depth: 0,
    };
    parser.expression()?;
    if parser.cursor != tokens.len() {
        return Err("unsupported compile-time expression syntax".into());
    }
    Ok(())
}

struct Syntax<'a> {
    tokens: &'a [Token],
    cursor: usize,
    depth: usize,
}

impl Syntax<'_> {
    fn symbol(&self, ch: char) -> bool {
        self.tokens
            .get(self.cursor)
            .is_some_and(|token| token_is_symbol(token, ch))
    }
    fn expect(&mut self, ch: char) -> EvalResult<()> {
        if !self.symbol(ch) {
            return Err(format!("compile-time expression expected `{ch}`"));
        }
        self.cursor += 1;
        Ok(())
    }
    fn expression(&mut self) -> EvalResult<()> {
        self.binary(0)?;
        if self.symbol('?') {
            self.cursor += 1;
            // Circom Expression13 branches are Expression12. A nested
            // conditional must therefore be parenthesized.
            self.binary(0)?;
            self.expect(':')?;
            self.binary(0)?;
        }
        Ok(())
    }
    fn binary(&mut self, minimum: u8) -> EvalResult<()> {
        if self.depth >= MAX_SYNTAX_DEPTH {
            return Err("compile-time expression syntax nesting limit".into());
        }
        self.depth += 1;
        let result = (|| {
            self.unary()?;
            while let Some((precedence, right)) = self
                .tokens
                .get(self.cursor)
                .and_then(|token| compile_time::operator_table(&super::token_to_text(token)))
                .map(|(_, precedence, right)| (precedence, right))
            {
                if precedence < minimum {
                    break;
                }
                self.cursor += 1;
                self.binary(if right { precedence } else { precedence + 1 })?;
            }
            Ok(())
        })();
        self.depth -= 1;
        result
    }
    fn unary(&mut self) -> EvalResult<()> {
        let mut prefixes = 0;
        while self.symbol('+') || self.symbol('-') || self.symbol('!') {
            prefixes += 1;
            self.cursor += 1;
            if prefixes >= MAX_SYNTAX_DEPTH {
                return Err("compile-time unary syntax nesting limit".into());
            }
        }
        let token = self
            .tokens
            .get(self.cursor)
            .ok_or("compile-time expression is empty")?;
        self.cursor += 1;
        match &token.kind {
            TokenKind::Number(_) => {}
            TokenKind::Identifier(name) => {
                if self.symbol('(') {
                    if ["assert", "log"].contains(&name.as_str()) {
                        return Err("assert/log are statements, not compile-time values".into());
                    }
                    self.cursor += 1;
                    self.list(')', true)?;
                }
            }
            TokenKind::Symbol('(') => {
                self.expression()?;
                self.expect(')')?;
            }
            TokenKind::Symbol('[') => self.list(']', false)?,
            _ => return Err("unsupported compile-time expression syntax".into()),
        }
        while self.symbol('[') {
            self.cursor += 1;
            self.expression()?;
            self.expect(']')?;
        }
        Ok(())
    }
    fn list(&mut self, closing: char, empty_allowed: bool) -> EvalResult<()> {
        if empty_allowed && self.symbol(closing) {
            self.cursor += 1;
            return Ok(());
        }
        loop {
            self.expression()?;
            if self.symbol(closing) {
                self.cursor += 1;
                return Ok(());
            }
            self.expect(',')?;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn functions(source: &str) -> Functions {
        Functions::from_sources(&[(PathBuf::from("pure.circom"), source.into())]).unwrap()
    }
    fn run(functions: &mut Functions, expression: &str) -> EvalResult<Value> {
        functions.eval(&lex(expression).unwrap(), &Env::new())
    }

    #[test]
    fn evaluates_source_log2ceil_with_bounded_while() {
        let mut f = functions("function log2Ceil(n) { var power=1; var bits=0; while(power<n){ power *= 2; bits++; } return bits; }");
        for (n, want) in [(0, 0), (1, 0), (2, 1), (3, 2), (8, 3), (9, 4)] {
            assert_eq!(
                run(&mut f, &format!("log2Ceil({n})")).unwrap(),
                Value::from(want)
            );
        }
    }

    #[test]
    fn evaluates_nested_calls_for_loops_and_local_array_assignments() {
        let mut f = functions("function twice(x){return x*2;} function build(n){var a[3]; for(var i=0;i<3;i++){a[i]=twice(n+i);} return a;} function sum(n){var x=0;for(var i=0;i<n;i+=1){x+=i;}return x;}");
        assert_eq!(run(&mut f, "build(2)[2]").unwrap(), Value::from(8));
        assert_eq!(run(&mut f, "sum(5)").unwrap(), Value::from(10));
    }

    #[test]
    fn evaluates_arrays_as_arguments_and_early_returns() {
        let mut f = functions("function pick(a,i){if(i==0){return a[0];}else{return a[1];}} function outer(n){var a[2]=[n,n+1];return pick(a,1);}");
        assert_eq!(run(&mut f, "outer(6)").unwrap(), Value::from(7));
        assert_eq!(run(&mut f, "pick([3,9],0)").unwrap(), Value::from(3));
    }

    #[test]
    fn unsupported_unused_functions_do_not_poison_valid_calls() {
        let mut f =
            functions("function bad(n){if(0){signal x;}return n;} function good(n){return n+1;}");
        assert_eq!(run(&mut f, "good(2)").unwrap(), Value::from(3));
        assert!(run(&mut f, "bad(2)").unwrap_err().contains("signals"));
    }

    #[test]
    fn validates_unsupported_statements_and_expressions_in_dead_branches() {
        for source in [
            "function f(n){if(0){log(n.foo);}return n;}",
            "function f(n){if(0){component c=Child();}return n;}",
            "function f(n){if(0){n.x=2;}return n;}",
            "function f(n){if(0){var x=n.foo;}return n;}",
            "function f(n){if(0){break;}return n;}",
        ] {
            assert!(run(&mut functions(source), "f(1)").is_err(), "{source}");
        }
    }

    #[test]
    fn duplicate_names_and_missing_values_fail_only_when_called() {
        let mut f = functions("function f(n){return n;} function f(n){return n+1;} function ok(){return 4;} function missing(){var a[2];a[0]=1;return a;}");
        assert_eq!(run(&mut f, "ok()").unwrap(), Value::from(4));
        assert!(run(&mut f, "f(1)").unwrap_err().contains("ambiguous"));
        assert!(run(&mut f, "missing()")
            .unwrap_err()
            .contains("uninitialized"));
        assert!(run(&mut f, "absent()").is_err());
        assert!(run(&mut f, "ok(1)").is_err());
        assert!(run(&mut functions("function f(){var x=1;}"), "f()").is_err());
    }

    #[test]
    fn recursion_and_infinite_loops_are_bounded() {
        assert!(run(&mut functions("function f(n){return f(n+1);}"), "f(1)")
            .unwrap_err()
            .contains("depth"));
        let mut f = functions("function f(){while(1){}return 0;}");
        f.remaining = 50;
        assert!(run(&mut f, "f()").unwrap_err().contains("budget"));
    }

    #[test]
    fn preserves_exact_division_and_rejects_scope_and_shape_ambiguity() {
        assert_eq!(
            run(&mut functions("function f(n){return n/2;}"), "f(8)").unwrap(),
            Value::from(4)
        );
        assert!(run(&mut functions("function f(n){return n/2;}"), "f(7)").is_err());
        assert!(run(
            &mut functions("function f(n){if(1){var n=2;}return n;}"),
            "f(1)"
        )
        .is_err());
        assert!(run(
            &mut functions("function f(){var x[2]=[1];return x;}"),
            "f()"
        )
        .is_err());
        assert!(run(
            &mut functions("function f(){var x[2];x[2]=1;return x;}"),
            "f()"
        )
        .is_err());
    }

    #[test]
    fn rejects_scalar_declarations_initialized_with_arrays() {
        assert!(
            run(&mut functions("function f(){var a=[1,2];return a;}"), "f()")
                .unwrap_err()
                .contains("shape")
        );
        assert!(
            run(&mut functions("function f(){var a[1]=2;return a;}"), "f()")
                .unwrap_err()
                .contains("shape")
        );
        assert_eq!(
            run(
                &mut functions("function f(){var a[2]=[1,2];return a[1];}"),
                "f()"
            )
            .unwrap(),
            Value::from(2)
        );
    }

    #[test]
    fn validates_transitive_purity_in_unreachable_function_calls() {
        let mut f=functions("function bad(){signal x;return 1;} function middle(){return bad();} function used(){if(0){var x=middle();}return 4;} function good(){return 5;}");
        assert_eq!(run(&mut f, "good()").unwrap(), Value::from(5));
        assert!(run(&mut f, "used()").unwrap_err().contains("signals"));
        let mut ambiguous=functions("function bad(){return 1;} function bad(){return 2;} function used(){if(0){return bad();}return 4;}");
        assert!(run(&mut ambiguous, "used()")
            .unwrap_err()
            .contains("ambiguous"));
    }

    #[test]
    fn purity_call_graph_cycles_terminate_before_runtime_recursion_checks() {
        let mut f = functions(
            "function a(n){if(n==0){return 1;}return b(n-1);} function b(n){return a(n);}",
        );
        assert_eq!(run(&mut f, "a(2)").unwrap(), Value::from(1));
        assert!(run(
            &mut functions("function a(){return b();} function b(){return a();}"),
            "a()"
        )
        .unwrap_err()
        .contains("depth"));
    }

    #[test]
    fn loop_locals_expire_but_updates_to_outer_variables_persist() {
        let mut f=functions("function f(){var s=0;for(var i=0;i<2;i++){var t=i+1;s+=t;}for(var i=0;i<3;i=i+1){s+=i;}return s;}");
        assert_eq!(run(&mut f, "f()").unwrap(), Value::from(6));
    }
    #[test]
    fn assertions_execute_only_on_reached_paths_and_report_exact_source_lines() {
        let source = "function checked(n) {\n if(n == 2) { return [3, 5]; }\n else {\n  assert(0);\n  return [0, 0];\n }\n}\nfunction outer(n) { return checked(n); }";
        assert_eq!(
            run(&mut functions(source), "checked(2)[1]").unwrap(),
            Value::from(5)
        );
        let error = run(&mut functions(source), "outer(3)").unwrap_err();
        assert!(
            error.contains("pure.circom:4: function checked: compile-time assert failed"),
            "{error}"
        );
        assert!(run(
            &mut functions("function f(){ assert([1]); return 1; }"),
            "f()"
        )
        .unwrap_err()
        .contains("scalar"));
        assert!(run(
            &mut functions("function f(){ assert(missing); return 1; }"),
            "f()"
        )
        .unwrap_err()
        .contains("unknown"));
    }

    #[test]
    fn assertion_truth_uses_bn128_field_normalization() {
        let prime = "21888242871839275222246405745257275088548364400416034343698204186575808495617";
        let source = format!("function f(n){{ assert(n); return 1; }} function bad(){{ assert({prime}); return 1; }}");
        assert!(run(&mut functions(&source), "bad()")
            .unwrap_err()
            .contains("assert failed"));
        assert_eq!(
            run(&mut functions(&source), "f(-1)").unwrap(),
            Value::from(1)
        );
        assert_eq!(
            run(
                &mut functions(&source),
                "f(21888242871839275222246405745257275088548364400416034343698204186575808495618)"
            )
            .unwrap(),
            Value::from(1)
        );
    }

    #[test]
    fn log_checks_arguments_without_output_or_return_value_changes() {
        let source = r#"function twice(n){return n*2;} function f(n){log("signal", n, twice(n), 21888242871839275222246405745257275088548364400416034343698204186575808495617);return n+1;}"#;
        assert_eq!(run(&mut functions(source), "f(4)").unwrap(), Value::from(5));
        for source in [
            "function f(){log(missing);return 1;}",
            "function f(){log([1]);return 1;}",
            "function f(){log();return 1;}",
            "function f(){assert(1,2);return 1;}",
            "function f(){if(0){return log(1);}return 1;}",
        ] {
            assert!(run(&mut functions(source), "f()").is_err(), "{source}");
        }
        let source = "function bad(){signal x;return 1;} function f(){if(0){log(bad());}return 1;}";
        assert!(run(&mut functions(source), "f()")
            .unwrap_err()
            .contains("signals"));
    }

    #[test]
    fn runtime_expression_errors_preserve_inner_function_location() {
        let source = "function inner(n) {\n var a[1] = [n];\n return a[2];\n}\nfunction outer(n) {\n return inner(n);\n}";
        let error = run(&mut functions(source), "outer(1)").unwrap_err();
        assert!(error.contains("pure.circom:3: function inner:"), "{error}");
        assert!(error.contains("out of range"), "{error}");
    }

    #[test]
    fn integer_compound_assignments_share_field_semantics() {
        let source = r"function f(){var x=-1; x \= 2; x %= 3; return x;}";
        assert_eq!(run(&mut functions(source), "f()").unwrap(), Value::from(0));
        let source = r"function f(){var x=7; x \= 0; return x;}";
        assert!(run(&mut functions(source), "f()")
            .unwrap_err()
            .contains("zero after field normalization"));
    }

    #[test]
    fn source_locations_preserve_the_existing_loop_step_budget() {
        let mut f = functions("function f(n){var s=0;for(var i=0;i<n;i++){s++;}return s;}");
        assert_eq!(run(&mut f, "f(12000)").unwrap(), Value::from(12000));
    }

    #[test]
    fn evaluates_ternaries_in_function_expressions_with_circom_precedence() {
        let source = "function max(a,b){return a>b ? a : b;} function f(n){var a[2]=[n ? max(3,5) : 1, 7]; var i=n ? 0 : 1; return a[i] + (n+1>3 ? n*2 : n+4);}";
        assert_eq!(
            run(&mut functions(source), "max(5,3)").unwrap(),
            Value::from(5)
        );
        assert_eq!(
            run(&mut functions(source), "f(0)").unwrap(),
            Value::from(11)
        );
        assert_eq!(
            run(&mut functions(source), "f(3)").unwrap(),
            Value::from(11)
        );
        let source = "function f(n){var a[2]=[3,7];return a[n ? 0 : 1];} function g(a,b){return a ? (b ? 2 : 3) : (b ? 4 : 5);}";
        assert_eq!(run(&mut functions(source), "f(0)").unwrap(), Value::from(7));
        assert_eq!(
            run(&mut functions(source), "g(1,0)").unwrap(),
            Value::from(3)
        );
        assert_eq!(
            run(&mut functions(source), "g(0,1)").unwrap(),
            Value::from(4)
        );
    }

    #[test]
    fn validates_ternary_shape_even_in_unreachable_statements() {
        for expression in ["1 ? 2 : 3 ? 4 : 5", "1 ? 2 ? 3 : 4 : 5", "1 ? 2", "1 ? : 2"] {
            let source = format!("function f(){{if(0){{return {expression};}}return 1;}}");
            assert!(run(&mut functions(&source), "f()").is_err(), "{expression}");
        }
        let source = "function f(){if(0){return 1 ? (0 ? 3 : 4) : 5;}return 1;}";
        assert_eq!(run(&mut functions(source), "f()").unwrap(), Value::from(1));
    }

    #[test]
    fn ternaries_refuse_non_scalar_or_unresolved_unselected_branches() {
        for expression in [
            "1 ? 2 : missing",
            "0 ? missing : 2",
            "1 ? 2 : (1 \\ 0)",
            "1 ? 2 : [3]",
            "0 ? [3] : 2",
        ] {
            let source = format!("function f(){{return {expression};}}");
            assert!(run(&mut functions(&source), "f()").is_err(), "{expression}");
        }
        let source = "function bad(){signal x;return 1;} function f(){if(0){return 1 ? 2 : bad();}return 3;}";
        assert!(run(&mut functions(source), "f()")
            .unwrap_err()
            .contains("signals"));
    }
}
