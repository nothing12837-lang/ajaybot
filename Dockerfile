FROM nousresearch/hermes-agent:latest

# Expose standard Hermes web dashboard and API ports
EXPOSE 7860
EXPOSE 8642

# Ensure Hugging Face non-root user (UID 1000) has write access
USER root
RUN mkdir -p /opt/data && chown -R 1000:1000 /opt/data
USER 1000

ENV PORT=7860
ENV HERMES_DASHBOARD=1

CMD ["gateway", "run"]
