//! Bounded, fail-closed inspection for cases the original inspector cannot resolve.
//! This module never invokes a compiler, witness generator, fuzzer, or judge.

use super::compile_time::{Env, Value};
use super::compile_time_functions::Functions;
use super::*;

type EvalResult<T> = std::result::Result<T, String>;

#[derive(Clone, Debug)]
enum Statement {
    Simple(Vec<Token>),
    Block(Vec<Statement>),
    If(Vec<Token>, Vec<Statement>, Vec<Statement>),
    For(Vec<Token>, Vec<Token>, Vec<Token>, Vec<Statement>),
    While(Vec<Token>, Vec<Statement>),
}

fn parse_statements(tokens: &[Token]) -> EvalResult<Vec<Statement>> {
    let mut result = Vec::new();
    let mut cursor = 0;
    while cursor < tokens.len() {
        if token_is_symbol(&tokens[cursor], ';') {
            cursor += 1;
            continue;
        }
        if token_is_symbol(&tokens[cursor], '{') {
            let end = find_matching(tokens, cursor, '{', '}').ok_or("unbalanced block")?;
            result.push(Statement::Block(parse_statements(
                &tokens[cursor + 1..end],
            )?));
            cursor = end + 1;
            continue;
        }
        let keyword = token_identifier(&tokens[cursor]);
        if matches!(keyword, Some("if" | "for" | "while")) {
            let open = cursor + 1;
            if !tokens.get(open).is_some_and(|t| token_is_symbol(t, '(')) {
                return Err("control flow requires a parenthesized header".into());
            }
            let close = find_matching(tokens, open, '(', ')').ok_or("unbalanced header")?;
            let (body_tokens, next) = control_body_tokens(tokens, close + 1)?;
            let body = parse_statements(body_tokens)?;
            let header = tokens[open + 1..close].to_vec();
            cursor = next;
            match keyword {
                Some("if") => {
                    let otherwise = if tokens
                        .get(cursor)
                        .is_some_and(|t| token_is_identifier(t, "else"))
                    {
                        let (body, next) = control_body_tokens(tokens, cursor + 1)?;
                        cursor = next;
                        parse_statements(body)?
                    } else {
                        Vec::new()
                    };
                    result.push(Statement::If(header, body, otherwise));
                }
                Some("for") => {
                    let clauses = split_top_level(&header, ';')?;
                    if clauses.len() != 3 || clauses.iter().any(Vec::is_empty) {
                        return Err("for requires three nonempty clauses".into());
                    }
                    result.push(Statement::For(
                        clauses[0].clone(),
                        clauses[1].clone(),
                        clauses[2].clone(),
                        body,
                    ));
                }
                Some("while") => result.push(Statement::While(header, body)),
                _ => unreachable!(),
            }
            continue;
        }
        let end = find_statement_end(tokens, cursor).ok_or("statement has no terminator")?;
        result.push(Statement::Simple(tokens[cursor..end].to_vec()));
        cursor = end + 1;
    }
    Ok(result)
}

fn statement_line(statement: &Statement) -> usize {
    match statement {
        Statement::Simple(tokens)
        | Statement::If(tokens, _, _)
        | Statement::For(tokens, _, _, _)
        | Statement::While(tokens, _) => tokens.first().map_or(1, |token| token.line),
        Statement::Block(body) => body.first().map_or(1, statement_line),
    }
}

fn identifiers(tokens: &[Token]) -> HashSet<String> {
    tokens
        .iter()
        .filter_map(token_identifier)
        .map(str::to_owned)
        .collect()
}

fn direct_assignment(tokens: &[Token]) -> Option<usize> {
    find_top_level_symbol(tokens, '=')
}

/// Only values that can affect instance resolution are interpreted in templates.
/// All function statements, in contrast, must pass the pure-function whitelist.
fn relevant(statement: &Statement, needed: &HashSet<String>) -> bool {
    match statement {
        Statement::Simple(tokens) => {
            tokens
                .first()
                .is_some_and(|t| token_is_identifier(t, "component"))
                || contains_possible_instantiation(tokens)
                || contains_anonymous_component_call(tokens)
                || (tokens
                    .first()
                    .is_some_and(|t| token_is_identifier(t, "var"))
                    && identifiers(tokens).iter().any(|n| needed.contains(n)))
                || tokens
                    .iter()
                    .take(2)
                    .filter_map(token_identifier)
                    .any(|n| needed.contains(n))
        }
        Statement::Block(body) | Statement::While(_, body) | Statement::For(_, _, _, body) => {
            body.iter().any(|s| relevant(s, needed))
        }
        Statement::If(_, yes, no) => yes.iter().chain(no).any(|s| relevant(s, needed)),
    }
}

fn close_needed(statements: &[Statement], needed: &mut HashSet<String>) {
    for statement in statements {
        match statement {
            Statement::Simple(tokens) if relevant(statement, needed) => {
                if let Ok(calls) = parse_anonymous_component_calls(tokens) {
                    for call in calls {
                        if let BodyItem::Instantiation { call, .. } = call {
                            for argument in call.arguments {
                                needed.extend(identifiers(&argument));
                            }
                        }
                    }
                }
                // Signal constraints do not affect compile-time bindings.
                if !tokens.iter().any(|t| matches!(&t.kind, TokenKind::Operator(op) if ["<==", "<--", "==>", "-->", "==="].contains(&op.as_str()))) {
                    needed.extend(identifiers(tokens));
                }
            }
            Statement::Block(body) => close_needed(body, needed),
            Statement::For(init, cond, update, body) if relevant(statement, needed) => {
                needed.extend(identifiers(init));
                needed.extend(identifiers(cond));
                needed.extend(identifiers(update));
                close_needed(body, needed);
            }
            Statement::While(cond, body) if relevant(statement, needed) => {
                needed.extend(identifiers(cond));
                close_needed(body, needed);
            }
            Statement::If(cond, yes, no) if relevant(statement, needed) => {
                needed.extend(identifiers(cond));
                close_needed(yes, needed);
                close_needed(no, needed);
            }
            _ => {}
        }
    }
}

#[derive(Default)]
struct Frame {
    values: Env,
    variables: HashMap<String, Vec<usize>>,
    components: HashMap<String, Vec<usize>>,
    initialized_components: HashSet<String>,
}

struct Interpreter<'a> {
    definitions: &'a HashMap<String, Vec<&'a TemplateDefinition>>,
    bodies: HashMap<(PathBuf, String), Vec<Statement>>,
    instances: Vec<InspectedTemplateInstance>,
    scopes: Vec<TemplateSourceScope>,
    active: HashSet<(PathBuf, String, Vec<String>)>,
    steps: usize,
    functions: Functions,
    source_contexts: Vec<(PathBuf, String, usize)>,
}

impl Interpreter<'_> {
    fn step(&mut self) -> EvalResult<()> {
        self.steps = self
            .steps
            .checked_sub(1)
            .ok_or("compile-time expansion budget exhausted")?;
        Ok(())
    }

    fn source_error(&self, line: usize, reason: String) -> String {
        if reason.starts_with("compile-time source ") {
            return reason;
        }
        match self.source_contexts.last() {
            Some((path, name, offset)) => format!(
                "compile-time source {}:{}: template {name}: {reason}",
                path.display(),
                line + offset
            ),
            None => reason,
        }
    }

    fn expression(&mut self, tokens: &[Token], frame: &Frame) -> EvalResult<Value> {
        self.step()?;
        self.functions
            .eval(tokens, &frame.values)
            .map_err(|reason| {
                self.source_error(tokens.first().map_or(1, |token| token.line), reason)
            })
    }

    fn dimensions(
        &mut self,
        tokens: &[Token],
        cursor: &mut usize,
        frame: &Frame,
    ) -> EvalResult<Vec<usize>> {
        let mut dims = Vec::new();
        let mut cells = 1usize;
        while tokens.get(*cursor).is_some_and(|t| token_is_symbol(t, '[')) {
            let close =
                find_matching(tokens, *cursor, '[', ']').ok_or("unbalanced array dimension")?;
            let value = self
                .expression(&tokens[*cursor + 1..close], frame)?
                .scalar()?;
            let size = usize::try_from(value).map_err(|_| "array dimension must be nonnegative")?;
            cells = cells.checked_mul(size).ok_or("array size overflow")?;
            if cells > MAX_TOTAL_EXPANSION_STEPS || dims.len() >= 64 {
                return Err("array exceeds inspection limit".into());
            }
            dims.push(size);
            *cursor = close + 1;
        }
        Ok(dims)
    }

    fn variable(&mut self, tokens: &[Token], frame: &mut Frame) -> EvalResult<()> {
        let declarations = split_top_level(&tokens[1..], ',')?;
        for declaration in declarations {
            let name = declaration
                .first()
                .and_then(token_identifier)
                .ok_or("variable name missing")?
                .to_owned();
            if frame.variables.contains_key(&name)
                || frame.values.contains_key(&name)
                || frame.components.contains_key(&name)
            {
                return Err(format!(
                    "shadowed or duplicate binding {name} is unsupported"
                ));
            }
            let mut cursor = 1;
            let dims = self.dimensions(&declaration, &mut cursor, frame)?;
            let value = if cursor == declaration.len() {
                Value::uninitialized(&dims)?
            } else if declaration
                .get(cursor)
                .is_some_and(|t| token_is_symbol(t, '='))
            {
                self.expression(&declaration[cursor + 1..], frame)?
            } else {
                return Err("unsupported variable declaration".into());
            };
            if value.dimensions()? != dims {
                return Err(format!("array declaration shape mismatch for {name}"));
            }
            frame.variables.insert(name.clone(), dims);
            frame.values.insert(name, value);
        }
        Ok(())
    }

    fn assignment(&mut self, tokens: &[Token], frame: &mut Frame) -> EvalResult<()> {
        for assignment in split_top_level(tokens, ',')? {
            let name = assignment
                .first()
                .and_then(token_identifier)
                .ok_or("assignment name missing")?
                .to_owned();
            if !frame.variables.contains_key(&name) {
                return Err(format!("assignment to unknown or parameter binding {name}"));
            }
            let mut cursor = 1;
            let indices = self.dimensions(&assignment, &mut cursor, frame)?;
            let remaining = &assignment[cursor..];
            let value = if remaining.first().is_some_and(|t| token_is_symbol(t, '=')) {
                self.expression(&remaining[1..], frame)?
            } else {
                let old = self.expression(&assignment[..cursor], frame)?;
                let (operator, rhs) = match remaining {
                    [Token {
                        kind: TokenKind::Operator(op),
                        ..
                    }] if op == "++" => ("+", Value::from(1)),
                    [Token {
                        kind: TokenKind::Operator(op),
                        ..
                    }] if op == "--" => ("-", Value::from(1)),
                    [op, equal, rest @ ..] if token_is_symbol(equal, '=') => {
                        let operation = match &op.kind {
                            TokenKind::Symbol('+') => "+",
                            TokenKind::Symbol('-') => "-",
                            TokenKind::Symbol('*') => "*",
                            TokenKind::Symbol('/') => "/",
                            TokenKind::Symbol('\\') => "\\",
                            TokenKind::Symbol('%') => "%",
                            TokenKind::Symbol('&') => "&",
                            TokenKind::Symbol('|') => "|",
                            TokenKind::Symbol('^') => "^",
                            TokenKind::Operator(op) if op == "<<" => "<<",
                            TokenKind::Operator(op) if op == ">>" => ">>",
                            _ => return Err("unsupported compound assignment".into()),
                        };
                        (operation, self.expression(rest, frame)?)
                    }
                    _ => return Err("unsupported compile-time assignment".into()),
                };
                super::compile_time::arithmetic_values(operator, &old, &rhs)?
            };
            frame
                .values
                .get_mut(&name)
                .ok_or("missing declared variable")?
                .set_index(&indices, value)?;
        }
        Ok(())
    }

    fn instantiate(
        &mut self,
        name: &str,
        arguments: &[Vec<Token>],
        frame: &Frame,
        depth: usize,
    ) -> EvalResult<()> {
        let values = arguments
            .iter()
            .map(|a| self.expression(a, frame))
            .collect::<EvalResult<Vec<_>>>()?;
        self.template(name, values, depth + 1)
    }

    fn component(&mut self, tokens: &[Token], frame: &mut Frame, depth: usize) -> EvalResult<()> {
        let declaration = tokens
            .first()
            .is_some_and(|t| token_is_identifier(t, "component"));
        let start = usize::from(declaration);
        let name = tokens
            .get(start)
            .and_then(token_identifier)
            .ok_or("component name missing")?
            .to_owned();
        let mut cursor = start + 1;
        let indices = self.dimensions(tokens, &mut cursor, frame)?;
        if declaration {
            if frame
                .components
                .insert(name.clone(), indices.clone())
                .is_some()
                || frame.values.contains_key(&name)
            {
                return Err(format!("component redeclaration {name} is unsupported"));
            }
            if cursor == tokens.len() {
                return Ok(());
            }
            if !indices.is_empty() {
                return Err("whole component-array initialization is unsupported".into());
            }
        } else {
            let dims = frame
                .components
                .get(&name)
                .ok_or("component assignment without declaration")?;
            if dims.len() != indices.len() || indices.iter().zip(dims).any(|(i, n)| i >= n) {
                return Err("component array index out of bounds or rank mismatch".into());
            }
        }
        if !tokens.get(cursor).is_some_and(|t| token_is_symbol(t, '=')) {
            // A component signal connection, not a component rebind.
            if tokens.get(cursor).is_some_and(|t| token_is_symbol(t, '.')) {
                return Ok(());
            }
            return Err("unsupported component assignment".into());
        }
        let slot = format!("{name}{indices:?}");
        if !frame.initialized_components.insert(slot) {
            return Err("component slot assigned more than once".into());
        }
        let call = parse_call(&tokens[cursor + 1..])?;
        self.instantiate(&call.template_name, &call.arguments, frame, depth)
    }

    fn simple(&mut self, tokens: &[Token], frame: &mut Frame, depth: usize) -> EvalResult<()> {
        let Some(first) = tokens.first() else {
            return Ok(());
        };
        if token_is_identifier(first, "var") {
            return self.variable(tokens, frame);
        }
        if token_is_identifier(first, "component") {
            return self.component(tokens, frame, depth);
        }
        if contains_anonymous_component_call(tokens) {
            for call in parse_anonymous_component_calls(tokens)? {
                if let BodyItem::Instantiation { call, .. } = call {
                    self.instantiate(&call.template_name, &call.arguments, frame, depth)?;
                } else {
                    return Err("unrecognized anonymous component".into());
                }
            }
            return Ok(());
        }
        if token_identifier(first).is_some_and(|name| frame.components.contains_key(name)) {
            return self.component(tokens, frame, depth);
        }
        if direct_assignment(tokens).is_some()
            || tokens
                .iter()
                .any(|t| matches!(&t.kind, TokenKind::Operator(op) if op == "++" || op == "--"))
        {
            return self.assignment(tokens, frame);
        }
        if token_is_identifier(first, "signal") || tokens.iter().any(|t| matches!(&t.kind, TokenKind::Operator(op) if ["<==", "<--", "==>", "-->", "==="].contains(&op.as_str()))) {
            return Ok(());
        }
        if token_identifier(first).is_some_and(|name| ["assert", "log"].contains(&name)) {
            return Ok(());
        }
        Err(format!(
            "unsupported inspection statement {}",
            tokens_to_text(tokens)
        ))
    }

    fn block(
        &mut self,
        statements: &[Statement],
        frame: &mut Frame,
        needed: &HashSet<String>,
        depth: usize,
    ) -> EvalResult<()> {
        for statement in statements {
            if !relevant(statement, needed) {
                continue;
            }
            self.step()?;
            let result = (|| {
                match statement {
                    Statement::Simple(tokens) => self.simple(tokens, frame, depth)?,
                    Statement::Block(body) => self.scoped_block(body, frame, needed, depth)?,
                    Statement::If(condition, yes, no) => {
                        let selected = if self.expression(condition, frame)?.scalar()? != 0 {
                            yes
                        } else {
                            no
                        };
                        self.scoped_block(selected, frame, needed, depth)?;
                    }
                    Statement::For(init, condition, update, body) => {
                        let old_values = frame.values.keys().cloned().collect::<HashSet<_>>();
                        if init.first().is_some_and(|t| token_is_identifier(t, "var")) {
                            self.variable(init, frame)?;
                        } else {
                            self.assignment(init, frame)?;
                        }
                        let mut iterations = 0;
                        while self.expression(condition, frame)?.scalar()? != 0 {
                            if iterations >= MAX_COMPILE_TIME_LOOP_ITERATIONS {
                                return Err("compile-time loop limit exceeded".into());
                            }
                            iterations += 1;
                            self.scoped_block(body, frame, needed, depth)?;
                            self.assignment(update, frame)?;
                        }
                        frame.values.retain(|name, _| old_values.contains(name));
                        frame.variables.retain(|name, _| old_values.contains(name));
                    }
                    Statement::While(_, _) => {
                        return Err("template while loops are unsupported".into())
                    }
                }
                Ok(())
            })();
            result.map_err(|reason| self.source_error(statement_line(statement), reason))?;
        }
        Ok(())
    }

    fn scoped_block(
        &mut self,
        statements: &[Statement],
        frame: &mut Frame,
        needed: &HashSet<String>,
        depth: usize,
    ) -> EvalResult<()> {
        let values = frame.values.keys().cloned().collect::<HashSet<_>>();
        let components = frame.components.keys().cloned().collect::<HashSet<_>>();
        self.block(statements, frame, needed, depth)?;
        frame.values.retain(|name, _| values.contains(name));
        frame.variables.retain(|name, _| values.contains(name));
        frame.components.retain(|name, _| components.contains(name));
        frame
            .initialized_components
            .retain(|slot| components.contains(slot.split('[').next().unwrap_or(slot)));
        Ok(())
    }

    fn template(&mut self, name: &str, values: Vec<Value>, depth: usize) -> EvalResult<()> {
        self.step()?;
        if depth >= MAX_INSTANTIATION_DEPTH {
            return Err("template depth limit exceeded".into());
        }
        let definitions = self
            .definitions
            .get(name)
            .ok_or_else(|| format!("unknown template {name}"))?;
        let [definition] = definitions.as_slice() else {
            return Err(format!("ambiguous template {name}"));
        };
        if definition.parameters.len() != values.len() {
            return Err(format!("template arity mismatch for {name}"));
        }
        let prime = num_bigint::BigUint::parse_bytes(
            b"21888242871839275222246405745257275088548364400416034343698204186575808495617",
            10,
        )
        .expect("bn128 prime");
        let parameters = values
            .iter()
            .map(|value| {
                let tokens = lex(&value.literal()).map_err(|(_, e)| e)?;
                literal_value(&tokens, &prime)?
                    .key_token(&prime)
                    .map_err(|e| e.to_string())
            })
            .collect::<EvalResult<Vec<_>>>()?;
        let key = (
            definition.source_path.clone(),
            name.to_owned(),
            parameters.clone(),
        );
        if !self.active.insert(key.clone()) {
            return Err("recursive concrete template instance".into());
        }
        let instance = InspectedTemplateInstance {
            path: definition.source_path.clone(),
            template_name: name.to_owned(),
            concrete_parameters: parameters,
        };
        if !self.instances.contains(&instance) {
            self.instances.push(instance);
        }
        let scope = TemplateSourceScope {
            path: definition.source_path.clone(),
            template_name: name.to_owned(),
            start_line: definition.start_line,
            end_line: definition.end_line,
        };
        if !self.scopes.contains(&scope) {
            self.scopes.push(scope);
        }
        let body_key = (definition.source_path.clone(), name.to_owned());
        if !self.bodies.contains_key(&body_key) {
            let source = fs::read_to_string(&definition.source_path).map_err(|e| e.to_string())?;
            let tokens =
                lex(&source[definition.start_byte..definition.end_byte]).map_err(|(_, e)| e)?;
            let open = tokens
                .iter()
                .position(|t| token_is_symbol(t, '{'))
                .ok_or("template body missing")?;
            let close = find_matching(&tokens, open, '{', '}').ok_or("template body unbalanced")?;
            self.bodies.insert(
                body_key.clone(),
                parse_statements(&tokens[open + 1..close])?,
            );
        }
        let body = self.bodies[&body_key].clone();
        let mut needed = HashSet::new();
        loop {
            let before = needed.len();
            close_needed(&body, &mut needed);
            if before == needed.len() {
                break;
            }
        }
        let mut frame = Frame {
            values: definition.parameters.iter().cloned().zip(values).collect(),
            ..Frame::default()
        };
        self.source_contexts.push((
            definition.source_path.clone(),
            name.to_owned(),
            definition.start_line.saturating_sub(1),
        ));
        let result = self
            .block(&body, &mut frame, &needed, depth)
            .map_err(|reason| self.source_error(1, reason));
        self.source_contexts.pop();
        result?;
        self.active.remove(&key);
        Ok(())
    }
}

pub(super) fn inspect(
    original: &EntrypointInspection,
    files: &HashMap<PathBuf, ParsedFile>,
    definitions: &HashMap<String, Vec<&TemplateDefinition>>,
) -> EvalResult<EntrypointInspection> {
    if original.unsupported.iter().any(|u| {
        u.construct == "source file"
            || u.construct.starts_with("include")
            || u.reason.contains("source lines overlap")
    }) {
        return Err("source closure or source attribution is ambiguous".into());
    }
    let file = files
        .get(&original.entrypoint)
        .ok_or("entrypoint was not parsed")?;
    let [main] = file.mains.as_slice() else {
        return Err("entrypoint must have one main".into());
    };
    let call = main.call.as_ref().ok_or("main call is unsupported")?;
    let mut paths = files.keys().cloned().collect::<Vec<_>>();
    paths.sort();
    let sources = paths
        .into_iter()
        .map(|path| {
            let source = fs::read_to_string(&path).map_err(|error| error.to_string())?;
            Ok((path, source))
        })
        .collect::<EvalResult<Vec<_>>>()?;
    let functions = Functions::from_sources(&sources)?;
    let mut interpreter = Interpreter {
        definitions,
        bodies: HashMap::new(),
        instances: Vec::new(),
        scopes: Vec::new(),
        active: HashSet::new(),
        steps: MAX_TOTAL_EXPANSION_STEPS,
        functions,
        source_contexts: Vec::new(),
    };
    let values = call
        .arguments
        .iter()
        .map(|a| interpreter.expression(a, &Frame::default()))
        .collect::<EvalResult<Vec<_>>>()?;
    interpreter.template(&call.template_name, values, 0)?;
    let root = interpreter.instances.first().cloned();
    interpreter.instances.sort_by(|a, b| {
        a.path
            .cmp(&b.path)
            .then(a.template_name.cmp(&b.template_name))
            .then(a.concrete_parameters.cmp(&b.concrete_parameters))
    });
    interpreter
        .scopes
        .sort_by(|a, b| a.path.cmp(&b.path).then(a.start_line.cmp(&b.start_line)));
    for scope in &interpreter.scopes {
        if files[&scope.path].templates.iter().any(|other| {
            other.name != scope.template_name
                && scope.start_line <= other.end_line
                && other.start_line <= scope.end_line
        }) {
            return Err("template source lines overlap another definition".into());
        }
    }
    Ok(EntrypointInspection {
        root,
        instances: interpreter.instances,
        scopes: interpreter.scopes,
        complete: true,
        unsupported: Vec::new(),
        ..original.clone()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inspect_source(source: &str) -> EntrypointInspection {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("main.circom");
        fs::write(&path, source).unwrap();
        inspect_entrypoint_with_libraries_and_prime(&path, dir.path(), &[], "bn128").unwrap()
    }

    #[test]
    fn array_arguments_and_local_arrays_resolve_nested_instances() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n var x[2][2] = [[1,2],[3,4]];\n component c = Child(a[1] + x[0][1]);\n}\ncomponent main = Parent([7,8]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["10"]));
    }

    #[test]
    fn source_functions_resolve_template_arguments() {
        let result = inspect_source("function log2Ceil(n) { var k=0; var p=1; while(p<n) { p=p*2; k++; } return k; }\ntemplate Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n component c=Child(log2Ceil(a[0]));\n}\ncomponent main=Parent([9]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["4"]));
    }

    #[test]
    fn disjoint_component_array_segments_follow_mutated_offsets() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n component c[4]; var offset=0;\n for(var i=0;i<2;i++) { c[offset+i]=Child(i); }\n offset += 2;\n for(var i=0,j=0;i<2;i++,j++) { c[offset+j]=Child(a[j]); }\n}\ncomponent main=Parent([7,8]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["8"]));
    }

    #[test]
    fn secondary_counter_and_uninitialized_array_are_resolved_in_order() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n var values[2]; component c[2]; var i=0;\n for(i=0;i<2;i++) { values[i]=a[i]+1; }\n for(var k=0,ii=0;k<32;k+=16) { c[ii]=Child(values[ii]); ii++; }\n}\ncomponent main=Parent([7,8]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["9"]));
    }

    #[test]
    fn overlapping_component_slots_and_scope_leaks_are_rejected() {
        for body in [
            "component c[2]; for(var i=0;i<2;i++) { c[0]=Child(a[0]); }",
            "if(1) { var x=1; } component c=Child(x+a[0]);",
        ] {
            let result=inspect_source(&format!("template Child(n) {{\n signal output out; out <== n;\n}}\ntemplate Parent(a) {{\n {body}\n}}\ncomponent main=Parent([0]);\n"));
            assert!(!result.complete);
        }
    }

    #[test]
    fn extended_inspection_requires_an_explicit_supported_prime() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("main.circom");
        fs::write(&path,"template Parent(a) {\n signal output out; out <== a[0];\n}\ncomponent main=Parent([0]);\n").unwrap();
        assert!(!inspect_entrypoint(&path, dir.path()).unwrap().complete);
        assert!(
            !inspect_entrypoint_with_libraries_and_prime(&path, dir.path(), &[], "goldilocks")
                .unwrap()
                .complete
        );
        assert!(
            inspect_entrypoint_with_libraries_and_prime(&path, dir.path(), &[], "bn128")
                .unwrap()
                .complete
        );
    }

    #[test]
    fn component_connections_include_anonymous_argument_dependencies() {
        let result = inspect_source("template Child(n) {\n signal input x; signal output out; out <== x+n;\n}\ntemplate Sink() {\n signal input x;\n}\ntemplate Parent(a) {\n var widths[1]=[2]; component sink=Sink();\n sink.x <== Child(widths[0])(a[0]);\n}\ncomponent main=Parent([0]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["2"]));
    }

    #[test]
    fn loop_local_components_have_fresh_scopes() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n for(var i=0;i<2;i++) { component local=Child(a[i]); }\n}\ncomponent main=Parent([1,2]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|i| i.template_name == "Child" && i.concrete_parameters == ["2"]));
    }

    #[test]
    fn array_shape_and_dynamic_index_fail_closed() {
        for expression in [
            "var x[3] = [1,2]; component c = Child(x[0]);",
            "var x[2] = [1,2]; component c = Child(x[2]);",
            "var x[2] = [1,2]; component c = Child(x[signal_value]);",
        ] {
            let result = inspect_source(&format!("template Child(n) {{\n signal output out; out <== n;\n}}\ntemplate Parent(a) {{\n {expression}\n}}\ncomponent main = Parent([0]);\n"));
            assert!(!result.complete);
        }
    }
    #[test]
    fn template_diagnostics_use_absolute_source_lines_without_mutating_tokens() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n var x = missing;\n component c = Child(x);\n}\ncomponent main = Parent([0]);\n");
        assert!(!result.complete);
        let reason = &result.unsupported[0].reason;
        assert!(
            reason.contains("main.circom:5: template Parent: unknown compile-time value missing"),
            "{reason}"
        );
    }

    #[test]
    fn function_assertion_failure_keeps_function_site_through_template_calls() {
        let result = inspect_source("function checked(n) {\n assert(n);\n return n;\n}\ntemplate Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n component c = Child(checked(a[0]));\n}\ncomponent main = Parent([0]);\n");
        assert!(!result.complete);
        let reason = &result.unsupported[0].reason;
        assert!(
            reason.contains("main.circom:2: function checked: compile-time assert failed"),
            "{reason}"
        );
    }

    #[test]
    fn template_integer_compound_assignments_use_the_same_field_arithmetic() {
        let result = inspect_source("template Child(n) {\n signal output out; out <== n;\n}\ntemplate Parent(a) {\n var x = a[0];\n x \\= 2;\n x %= 3;\n component c = Child(x);\n}\ncomponent main = Parent([7]);\n");
        assert!(result.complete, "{:?}", result.unsupported);
        assert!(result
            .instances
            .iter()
            .any(|instance| instance.template_name == "Child"
                && instance.concrete_parameters == ["0"]));
    }
}
