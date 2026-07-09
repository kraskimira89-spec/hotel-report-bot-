import { Panel, Container, Flex, Typography } from "@maxhub/max-ui";
import { getInitDataUnsafe, getPlatform } from "./bridge";

export default function App() {
  const init = getInitDataUnsafe();
  const userName = init.user
    ? [init.user.first_name, init.user.last_name].filter(Boolean).join(" ")
    : "Гость";

  return (
    <Panel mode="secondary" className="panel">
      <Container>
        <Flex direction="column" gap={12}>
          <Typography.Headline>1apart — отчёты</Typography.Headline>
          <Typography.Body>
            Платформа: {getPlatform()}
          </Typography.Body>
          <Typography.Body>
            Пользователь: {userName || "—"}
          </Typography.Body>
          {init.chat?.id != null && (
            <Typography.Label>chat_id: {init.chat.id}</Typography.Label>
          )}
          <Typography.Label>
            Мини-приложение: MAX Bridge + MAX UI
          </Typography.Label>
        </Flex>
      </Container>
    </Panel>
  );
}
