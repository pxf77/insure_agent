from backend.app.schemas import SignalCandidate


class ConsoleNotificationProvider:
    def notify(self, candidate: SignalCandidate, signal_id: int) -> None:
        price_range = candidate.price_range or (0.0, 0.0)
        print(
            "\n".join(
                [
                    f"Signal #{signal_id}: {candidate.symbol} {candidate.action.upper()}",
                    f"Score: {candidate.score}, confidence: {candidate.confidence:.2f}",
                    f"Suggested range: {price_range[0]:.2f}-{price_range[1]:.2f}",
                    f"Stop loss: {candidate.stop_loss}, take profit: {candidate.take_profit}",
                    "manual confirmation required",
                    "not an automatic order instruction",
                ],
            ),
        )
