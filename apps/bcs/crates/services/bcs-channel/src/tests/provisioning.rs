use super::*;

#[tokio::test]
async fn provisioned_conversation_reuses_bcs_session_for_first_group_message() -> TestResult {
    let harness = TestHarness::new(chat_group("unrelated_group")).await?;
    harness
        .binding_repo
        .create(active_binding(
            "binding_1",
            "robot_1",
            BindingTarget::Bot {
                bot_id: "target_bot".to_string(),
            },
            Visibility::LeadOnly,
        ))
        .await?;

    let command = ProvisionChannelConversationCommand {
        channel_type: channel_type(),
        account_ref: "robot_1".to_string(),
        im_conversation_id: "conv_shared".to_string(),
        im_conversation_type: "2".to_string(),
        engine_session_key: "user:136677:session:session-a:agent:target_bot".to_string(),
    };
    let provisioned = harness
        .service
        .provision_conversation(command.clone())
        .await?;
    assert!(provisioned.created);

    let session = harness
        .session_repo
        .get(&provisioned.bcs_session_id)
        .await
        .expect("provisioned session");
    assert_eq!(session.status, SessionStatus::Running);
    assert_eq!(
        session.meta.as_ref()
            .and_then(|meta| meta.pointer("/channel/engine_session_key"))
            .and_then(serde_json::Value::as_str),
        Some("user:136677:session:session-a:agent:target_bot")
    );
    assert_eq!(
        session.meta.as_ref()
            .and_then(|meta| meta.pointer("/channel/engine_bot_id"))
            .and_then(serde_json::Value::as_str),
        Some("target_bot")
    );

    let repeated = harness.service.provision_conversation(command).await?;
    assert!(!repeated.created);
    assert_eq!(repeated.bcs_session_id, provisioned.bcs_session_id);
    assert_eq!(harness.session_repo.sessions.lock().await.len(), 1);

    harness
        .service
        .handle_inbound(group_inbound(
            "conv_shared",
            "u1",
            Some("张三"),
            "msg_1",
            true,
        ))
        .await?;

    assert_eq!(harness.session_repo.sessions.lock().await.len(), 1);
    let sends = harness.message_flow.web_sends.lock().await;
    assert_eq!(sends.len(), 1);
    assert_eq!(sends[0].session_id.as_deref(), Some(provisioned.bcs_session_id.as_str()));
    drop(sends);

    harness
        .session_repo
        .sessions
        .lock()
        .await
        .get_mut(&provisioned.bcs_session_id)
        .expect("provisioned session")
        .status = SessionStatus::Completed;
    harness
        .service
        .handle_inbound(group_inbound(
            "conv_shared",
            "u2",
            Some("李四"),
            "msg_2",
            true,
        ))
        .await?;
    let sessions = harness.session_repo.sessions.lock().await;
    assert_eq!(sessions.len(), 2);
    let replacement = sessions
        .values()
        .find(|session| session.status == SessionStatus::Running)
        .expect("replacement running session");
    assert_eq!(
        replacement.meta.as_ref()
            .and_then(|meta| meta.pointer("/channel/engine_session_key"))
            .and_then(serde_json::Value::as_str),
        Some("user:136677:session:session-a:agent:target_bot")
    );
    Ok(())
}

#[tokio::test]
async fn provisioned_conversation_rejects_conflicting_engine_session() -> TestResult {
    let harness = TestHarness::new(chat_group("unrelated_group")).await?;
    harness
        .binding_repo
        .create(active_binding(
            "binding_1",
            "robot_1",
            BindingTarget::Bot {
                bot_id: "target_bot".to_string(),
            },
            Visibility::LeadOnly,
        ))
        .await?;

    let base = ProvisionChannelConversationCommand {
        channel_type: channel_type(),
        account_ref: "robot_1".to_string(),
        im_conversation_id: "conv_shared".to_string(),
        im_conversation_type: "2".to_string(),
        engine_session_key: "engine-session-a".to_string(),
    };
    harness.service.provision_conversation(base.clone()).await?;
    let error = harness
        .service
        .provision_conversation(ProvisionChannelConversationCommand {
            engine_session_key: "engine-session-b".to_string(),
            ..base
        })
        .await
        .expect_err("conflicting engine session must be rejected");
    assert!(matches!(error, ChannelUseCaseError::Conflict(_)));
    Ok(())
}
